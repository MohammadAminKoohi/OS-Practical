package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func cloudInitReady(output string, code int) (bool, error) {
	if code != 0 && code != 2 {
		return false, fmt.Errorf("cloud-init failed (exit %d)", code)
	}
	var status map[string]any
	start := strings.Index(output, "{")
	if start < 0 || json.Unmarshal([]byte(output[start:]), &status) != nil || status["status"] != "done" {
		return false, fmt.Errorf("cloud-init has not completed successfully")
	}
	var hasErrors func(any) bool
	hasErrors = func(value any) bool {
		switch v := value.(type) {
		case map[string]any:
			for key, child := range v {
				if key == "errors" {
					if items, ok := child.([]any); !ok || len(items) != 0 {
						return true
					}
				} else if hasErrors(child) {
					return true
				}
			}
		case []any:
			for _, child := range v {
				if hasErrors(child) {
					return true
				}
			}
		}
		return false
	}
	if hasErrors(status) {
		return false, fmt.Errorf("cloud-init reported provisioning errors")
	}
	return code == 2, nil
}

type vmConfig struct {
	Name, Owner, Profile string
	Created              bool
}

type instance struct{ Name, State string }

func loadConfig(state string) (vmConfig, error) {
	data, err := os.ReadFile(filepath.Join(state, "vm.json"))
	if err != nil {
		return vmConfig{}, err
	}
	var cfg vmConfig
	err = json.Unmarshal(data, &cfg)
	if err == nil && (cfg.Name == "" || cfg.Owner == "") {
		err = fmt.Errorf("invalid VM ownership configuration")
	}
	return cfg, err
}

func (a *App) instances(ctx context.Context) (map[string]string, error) {
	out, err := a.capture(ctx, "multipass", "list", "--format", "json")
	if err != nil {
		return nil, err
	}
	var response struct{ List []instance }
	if err = json.Unmarshal([]byte(out), &response); err != nil {
		return nil, fmt.Errorf("invalid Multipass list response: %w", err)
	}
	states := map[string]string{}
	for _, inst := range response.List {
		states[inst.Name] = inst.State
	}
	return states, nil
}

func (a *App) verifyOwner(ctx context.Context, cfg vmConfig) error {
	out, err := a.capture(ctx, "multipass", "exec", cfg.Name, "--", "cat", "/etc/langar-lab-owner")
	if err != nil || strings.TrimSpace(out) != cfg.Owner {
		return fmt.Errorf("refusing to use instance %q: ownership marker does not match this state directory", cfg.Name)
	}
	return nil
}

func cloudInit(cfg vmConfig) string {
	return fmt.Sprintf(`#cloud-config
package_update: true
packages:
  - build-essential
  - python3
  - procps
  - util-linux
  - tar
  - busybox-static
  - strace
  - bubblewrap
write_files:
  - path: /etc/langar-lab-owner
    content: '%s'
  - path: /etc/langar-lab-profile
    content: '%s'
runcmd:
  - [mkdir, -p, /var/lib/langar-lab]
  - [touch, /var/lib/langar-lab/ready]
`, cfg.Owner, Profile)
}

func (a *App) ensureVM(ctx context.Context, o options) (vmConfig, error) {
	ctx, cancel := context.WithTimeout(ctx, o.Timeout)
	defer cancel()
	states, err := a.instances(ctx)
	if err != nil {
		return vmConfig{}, err
	}
	cfg, err := loadConfig(o.State)
	if os.IsNotExist(err) {
		nonce := token()
		owner := "lab-" + nonce
		name := o.Instance
		if name == "" {
			name = "langar-lab-" + nonce[:8]
		}
		if _, exists := states[name]; exists {
			return vmConfig{}, fmt.Errorf("instance %q already exists; choose a new dedicated name", name)
		}
		cfg = vmConfig{Name: name, Owner: owner, Profile: Profile}
		if err = writeJSON(filepath.Join(o.State, "vm.json"), cfg); err != nil {
			return cfg, err
		}
	} else if err != nil {
		return cfg, err
	}
	if o.Instance != "" && cfg.Name != o.Instance {
		return cfg, fmt.Errorf("state belongs to %q, not %q; use a different --state-dir", cfg.Name, o.Instance)
	}
	if cfg.Profile != Profile {
		return cfg, fmt.Errorf("course profile changed; run langar-lab reset for this state directory")
	}
	state, exists := states[cfg.Name]
	if !exists {
		path := filepath.Join(o.State, "cloud-init.yaml")
		if err = os.WriteFile(path, []byte(cloudInit(cfg)), 0600); err != nil {
			return cfg, err
		}
		fmt.Fprintf(a.Out, "==> Creating dedicated Ubuntu 24.04 VM %s\n", cfg.Name)
		code, runErr := a.Exec.Run(ctx, "multipass", []string{"launch", "24.04", "--name", cfg.Name,
			"--cpus", fmt.Sprint(o.CPUs), "--memory", o.Memory, "--disk", o.Disk,
			"--cloud-init", path, "--timeout", fmt.Sprint(int(o.Timeout.Seconds()))}, nil, a.Out, a.Err)
		if runErr != nil || code != 0 {
			return cfg, fmt.Errorf("VM launch failed (exit %d): %v; check Multipass service, image download and virtualization", code, runErr)
		}
		cfg.Created = true
		if err = writeJSON(filepath.Join(o.State, "vm.json"), cfg); err != nil {
			return cfg, err
		}
	} else {
		if state != "Running" {
			if !cfg.Created {
				return cfg, fmt.Errorf("refusing to start unverified instance %q", cfg.Name)
			}
			if _, err = a.capture(ctx, "multipass", "start", cfg.Name); err != nil {
				return cfg, err
			}
		}
		if err = a.verifyOwner(ctx, cfg); err != nil {
			return cfg, err
		}
	}
	fmt.Fprintln(a.Out, "==> Checking Linux provisioning (first setup may take several minutes)")
	var status, statusErr bytes.Buffer
	code, runErr := a.Exec.Run(ctx, "multipass", []string{"exec", cfg.Name, "--", "sudo", "cloud-init", "status", "--wait", "--format", "json"}, nil, &status, &statusErr)
	_ = os.WriteFile(filepath.Join(o.State, "cloud-init-status.json"), status.Bytes(), 0600)
	warning, readinessErr := cloudInitReady(status.String(), code)
	if runErr != nil || readinessErr != nil {
		return cfg, fmt.Errorf("guest provisioning failed: %v %v %s; inspect 'multipass exec %s -- sudo cloud-init status --long'", runErr, readinessErr, statusErr.String(), cfg.Name)
	}
	if warning {
		fmt.Fprintln(a.Out, "NOTE cloud-init completed with recoverable warnings; checking required tools and profile. Details: cloud-init-status.json")
	}
	if err = a.verifyOwner(ctx, cfg); err != nil {
		return cfg, err
	}
	profile, err := a.capture(ctx, "multipass", "exec", cfg.Name, "--", "cat", "/etc/langar-lab-profile")
	if err != nil || strings.TrimSpace(profile) != Profile {
		return cfg, fmt.Errorf("guest course profile mismatch")
	}
	if _, err = a.capture(ctx, "multipass", "exec", cfg.Name, "--", "test", "-f", "/var/lib/langar-lab/ready"); err != nil {
		return cfg, fmt.Errorf("guest provisioning did not finish the course setup: %w", err)
	}
	// Upgrade an owned HW2 VM in place; preserve its ownership and host reports.
	if _, err = a.capture(ctx, "multipass", "exec", cfg.Name, "--", "test", "-x", "/usr/bin/bwrap"); err != nil {
		fmt.Fprintln(a.Out, "==> Installing semester fixture tools in owned course VM")
		code, installErr := a.Exec.Run(ctx, "multipass", []string{"exec", cfg.Name, "--", "sudo", "-n", "apt-get", "install", "-y", "busybox-static", "strace", "bubblewrap"}, nil, a.Out, a.Err)
		if installErr != nil || code != 0 {
			return cfg, fmt.Errorf("fixture tools install failed: %v (exit %d)", installErr, code)
		}
	}
	if _, err = a.capture(ctx, "multipass", "exec", cfg.Name, "--", "python3", "-c", environmentScript, "gcc"); err != nil {
		return cfg, err
	}
	if _, err = a.capture(ctx, "multipass", "exec", cfg.Name, "--", "sudo", "-n", "unshare", "--mount", "--pid", "--fork", "/bin/true"); err != nil {
		return cfg, fmt.Errorf("VM namespace preflight failed: %w", err)
	}
	cfg.Created = true
	if err = writeJSON(filepath.Join(o.State, "vm.json"), cfg); err != nil {
		return cfg, err
	}
	fmt.Fprintf(a.Out, "PASS environment %s\n", Profile)
	return cfg, nil
}

func (a *App) manage(ctx context.Context, command string, o options) error {
	if o.Backend == "native" {
		if command == "status" {
			return a.doctor(ctx, o)
		}
		return fmt.Errorf("%s manages a VM; select --backend multipass", command)
	}
	cfg, err := loadConfig(o.State)
	if err != nil {
		return fmt.Errorf("no course VM configured; run setup: %w", err)
	}
	if o.Instance != "" && o.Instance != cfg.Name {
		return fmt.Errorf("instance does not match state directory")
	}
	states, err := a.instances(ctx)
	if err != nil {
		return err
	}
	if command == "status" {
		state := states[cfg.Name]
		if state == "" {
			state = "Not present"
		}
		fmt.Fprintf(a.Out, "%s: %s (profile %s)\n", cfg.Name, state, cfg.Profile)
		return nil
	}
	unlock, err := lock(o.State)
	if err != nil {
		return err
	}
	defer unlock()
	if states[cfg.Name] == "" {
		if command == "reset" {
			_, err = a.ensureVM(ctx, o)
			return err
		}
		return fmt.Errorf("course VM no longer exists; run setup")
	}
	if states[cfg.Name] != "Running" {
		if !cfg.Created {
			return fmt.Errorf("cannot start unverified instance")
		}
		if _, err = a.capture(ctx, "multipass", "start", cfg.Name); err != nil {
			return err
		}
	}
	if err = a.verifyOwner(ctx, cfg); err != nil {
		return err
	}
	switch command {
	case "shell":
		code, err := a.Exec.Run(ctx, "multipass", []string{"shell", cfg.Name}, a.In, a.Out, a.Err)
		if err != nil || code != 0 {
			return fmt.Errorf("shell ended with %d: %v", code, err)
		}
	case "stop":
		_, err = a.capture(ctx, "multipass", "stop", cfg.Name)
		return err
	case "reset":
		fmt.Fprintf(a.Out, "==> Recreating owned course VM %s; source files on the host are unchanged\n", cfg.Name)
		// Never use a global 'purge': it could delete unrelated instances.
		resetCtx, cancel := context.WithTimeout(ctx, 2*time.Minute)
		defer cancel()
		if _, err = a.capture(resetCtx, "multipass", "delete", "--purge", cfg.Name); err != nil {
			return err
		}
		cfg.Profile, cfg.Created = Profile, false
		if err = writeJSON(filepath.Join(o.State, "vm.json"), cfg); err != nil {
			return err
		}
		_, err = a.ensureVM(ctx, o)
		return err
	}
	return nil
}
