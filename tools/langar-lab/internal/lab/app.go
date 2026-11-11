package lab

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type App struct {
	In       io.Reader
	Out, Err io.Writer
	Exec     Executor
	HostOS   string
}

type options struct {
	Backend, State, Instance, Memory, Disk, Source, CC, JSON string
	CPUs                                                     int
	Timeout                                                  time.Duration
	Assignment                                               string
	KeepWork                                                 bool
}

func New(in io.Reader, out, errOut io.Writer) *App {
	return &App{In: in, Out: out, Err: errOut, Exec: OSExecutor{}, HostOS: runtime.GOOS}
}

func (a *App) usage() {
	fmt.Fprintln(a.Out, `Langar Lab — Linux build and test environment

  langar-lab doctor [--backend auto|native|multipass]
  langar-lab setup  [--backend auto|native|multipass]
  langar-lab test hwN --source ./q2 [--backend auto|native|multipass] [--json FILE]
  langar-lab status | shell | stop | reset [--backend multipass]

Linux defaults to native. macOS/Windows default to Multipass.
Options: --state-dir DIR, --instance NAME, --timeout DURATION
Setup/reset: --cpus 2 --memory 2G --disk 12G
Test: --cc gcc (compiler inside Linux); --timeout 2m

Exit codes: 0 passed, 1 test failures, 2 environment/usage error,
            3 build failure, 130 interrupted.
HW2-HW8 are supported. All judges use sudo to supervise isolated, unprivileged student code.
Reset recreates only the owned course VM.`)
}

func (a *App) parse(command string, args []string) (options, error) {
	state, err := os.UserCacheDir()
	if err != nil {
		state = "."
	}
	o := options{}
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	fs.SetOutput(a.Err)
	fs.StringVar(&o.Backend, "backend", "auto", "auto, native, or multipass")
	fs.StringVar(&o.State, "state-dir", filepath.Join(state, "langar-lab"), "CLI-owned state and results")
	fs.StringVar(&o.Instance, "instance", "", "dedicated Multipass instance name")
	fs.StringVar(&o.Memory, "memory", "2G", "VM memory")
	fs.StringVar(&o.Disk, "disk", "12G", "VM disk")
	fs.IntVar(&o.CPUs, "cpus", 2, "VM CPUs")
	fs.StringVar(&o.Source, "source", "./q2", "source directory containing Makefile")
	fs.StringVar(&o.CC, "cc", "gcc", "Linux compiler executable")
	fs.StringVar(&o.JSON, "json", "", "also save a JSON report")
	fs.BoolVar(&o.KeepWork, "keep-work", false, "retain Linux workspace for debugging")
	defaultTimeout := 15 * time.Minute
	if command == "test" {
		defaultTimeout = 2 * time.Minute
	}
	fs.DurationVar(&o.Timeout, "timeout", defaultTimeout, "setup or overall build/test timeout")
	if err = fs.Parse(args); err != nil {
		return o, err
	}
	if fs.NArg() != 0 {
		return o, fmt.Errorf("unexpected arguments: %s", strings.Join(fs.Args(), " "))
	}
	if o.Backend == "auto" {
		o.Backend = "multipass"
		if a.HostOS == "linux" {
			o.Backend = "native"
		}
	}
	if o.Backend != "native" && o.Backend != "multipass" {
		return o, fmt.Errorf("unknown backend %q", o.Backend)
	}
	if o.Backend == "native" && a.HostOS != "linux" {
		return o, fmt.Errorf("native requires Linux; use --backend multipass on %s", a.HostOS)
	}
	if o.Timeout < time.Second || o.CPUs < 1 {
		return o, fmt.Errorf("timeout must be at least 1s and VM CPUs at least 1")
	}
	if !regexp.MustCompile(`^[1-9][0-9]*([.][0-9]+)?[KMG]?$`).MatchString(o.Memory) ||
		!regexp.MustCompile(`^[1-9][0-9]*([.][0-9]+)?[KMG]?$`).MatchString(o.Disk) {
		return o, fmt.Errorf("memory/disk must be positive sizes such as 2G and 12G")
	}
	if o.CC == "" || strings.ContainsAny(o.CC, " \t\r\n") {
		return o, fmt.Errorf("--cc must name a Linux compiler executable without arguments")
	}
	if o.Instance != "" && !regexp.MustCompile(`^[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?$`).MatchString(o.Instance) {
		return o, fmt.Errorf("invalid Multipass instance name")
	}
	o.State, err = filepath.Abs(o.State)
	return o, err
}

func (a *App) Run(ctx context.Context, args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" {
		a.usage()
		return 0
	}
	if args[0] == "version" || args[0] == "--version" {
		fmt.Fprintf(a.Out, "langar-lab %s (profile %s)\n", Version, Profile)
		return 0
	}
	command, rest := args[0], args[1:]
	assignment := "hw2"
	switch command {
	case "test":
		if len(rest) == 0 {
			fmt.Fprintln(a.Err, "Specify an assignment: langar-lab test hw2 --source ./q2")
			return 2
		}
		value := strings.TrimPrefix(strings.ToLower(rest[0]), "hw")
		number, parseErr := strconv.Atoi(value)
		if parseErr != nil || number < 2 || number > 8 {
			fmt.Fprintln(a.Err, "Choose hw2 through hw8")
			return 2
		}
		assignment = fmt.Sprintf("hw%d", number)
		rest = rest[1:]
	case "doctor", "setup", "status", "shell", "stop", "reset":
	default:
		fmt.Fprintf(a.Err, "Unknown command %q; run langar-lab help\n", command)
		return 2
	}
	o, err := a.parse(command, rest)
	o.Assignment = assignment
	if errors.Is(err, flag.ErrHelp) {
		return 0
	}
	if err != nil {
		fmt.Fprintln(a.Err, err)
		return 2
	}
	if command == "test" {
		return a.test(ctx, o)
	}
	if command == "doctor" {
		err = a.doctor(ctx, o)
	} else if command == "setup" {
		err = a.setup(ctx, o)
	} else {
		err = a.manage(ctx, command, o)
	}
	if err != nil {
		if ctx.Err() != nil {
			fmt.Fprintln(a.Err, "Interrupted")
			return 130
		}
		fmt.Fprintln(a.Err, err)
		return 2
	}
	return 0
}

func (a *App) capture(ctx context.Context, name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	var out, errs bytes.Buffer
	code, err := a.Exec.Run(ctx, name, args, nil, &out, &errs)
	if err != nil {
		return "", fmt.Errorf("%s: %w", name, err)
	}
	if code != 0 {
		return "", fmt.Errorf("%s failed (%d): %s%s", name, code, out.String(), errs.String())
	}
	return out.String(), nil
}

const environmentScript = `import json,platform,shutil,subprocess,sys
assert sys.platform == 'linux', 'Linux is required'
assert sys.version_info >= (3,10), 'Python 3.10+ required'
cc=sys.argv[1]
for p in (cc,'make','bwrap'):
 assert shutil.which(p), 'Missing '+p
print(json.dumps(dict(system=platform.system(),kernel=platform.release(),architecture=platform.machine(),python=platform.python_version(),compiler=subprocess.check_output([cc,'--version'],text=True).splitlines()[0])))`

func (a *App) doctor(ctx context.Context, o options) error {
	fmt.Fprintf(a.Out, "Backend: %s (host %s/%s)\n", o.Backend, a.HostOS, runtime.GOARCH)
	if o.Backend == "native" {
		out, err := a.capture(ctx, "python3", "-c", environmentScript, o.CC)
		if err != nil {
			return fmt.Errorf("native tools unavailable; install GCC, Make, Bubblewrap and Python 3.10+: %w", err)
		}
		fmt.Fprintln(a.Out, strings.TrimSpace(out))
		return nil
	}
	out, err := a.capture(ctx, "multipass", "version")
	if err != nil {
		return fmt.Errorf("Multipass is required and its service must be running: %w", err)
	}
	fmt.Fprintln(a.Out, strings.Split(out, "\n")[0])
	if _, err = a.instances(ctx); err != nil {
		return err
	}
	fmt.Fprintln(a.Out, "PASS Multipass service reachable")
	cfg, err := loadConfig(o.State)
	if os.IsNotExist(err) {
		fmt.Fprintln(a.Out, "Course VM not yet set up; run langar-lab setup")
		return nil
	}
	if err != nil {
		return err
	}
	fmt.Fprintf(a.Out, "Course instance: %s\n", cfg.Name)
	return nil
}

func lock(state string) (func(), error) {
	if err := os.MkdirAll(state, 0700); err != nil {
		return nil, err
	}
	path := filepath.Join(state, "operation.lock")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, fmt.Errorf("another operation owns %s; if a previous CLI crashed, remove that lock after checking it is no longer running", path)
	}
	fmt.Fprintf(f, "pid=%d\n", os.Getpid())
	f.Close()
	return func() { _ = os.Remove(path) }, nil
}

func (a *App) setup(ctx context.Context, o options) error {
	if o.Backend == "native" {
		return a.doctor(ctx, o)
	}
	unlock, err := lock(o.State)
	if err != nil {
		return err
	}
	defer unlock()
	_, err = a.ensureVM(ctx, o)
	return err
}
