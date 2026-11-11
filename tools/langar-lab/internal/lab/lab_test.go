package lab

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type call struct {
	Name string
	Args []string
}

type fakeExecutor struct {
	Calls []call
	Hook  func(string, []string) (string, int, error)
}

func (f *fakeExecutor) Run(_ context.Context, name string, args []string, _ io.Reader, out, _ io.Writer) (int, error) {
	f.Calls = append(f.Calls, call{name, append([]string{}, args...)})
	if f.Hook == nil {
		return 0, nil
	}
	text, code, err := f.Hook(name, args)
	io.WriteString(out, text)
	return code, err
}

func appForTest(host string) (*App, *fakeExecutor, *bytes.Buffer) {
	buffer := &bytes.Buffer{}
	fake := &fakeExecutor{}
	a := New(strings.NewReader(""), buffer, buffer)
	a.HostOS, a.Exec = host, fake
	return a, fake, buffer
}

func TestBackendSelection(t *testing.T) {
	for _, entry := range []struct{ host, backend string }{{"linux", "native"}, {"darwin", "multipass"}, {"windows", "multipass"}} {
		a, _, _ := appForTest(entry.host)
		o, err := a.parse("test", nil)
		if err != nil || o.Backend != entry.backend {
			t.Fatalf("%s: %+v %v", entry.host, o, err)
		}
	}
	a, _, _ := appForTest("darwin")
	if _, err := a.parse("test", []string{"--backend", "native"}); err == nil {
		t.Fatal("native accepted on macOS")
	}
}

func TestArgumentValidation(t *testing.T) {
	a, fake, _ := appForTest("linux")
	for _, args := range [][]string{{"test"}, {"test", "hw9"}, {"setup", "--backend", "invalid"},
		{"test", "hw2", "--timeout", "0s"}, {"setup", "--instance", "other; rm"}, {"setup", "--memory", "0G"}} {
		if code := a.Run(context.Background(), args); code != 2 {
			t.Fatalf("%v returned %d", args, code)
		}
	}
	if len(fake.Calls) != 0 {
		t.Fatal("invalid CLI invoked backend")
	}
	if _, err := a.parse("setup", []string{"--memory", "2.5G", "--instance", "a"}); err != nil {
		t.Fatal(err)
	}
}

func fixtureSource(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "source with spaces سلام")
	for _, rel := range []string{"Makefile", "src/main.c", "src/run.c", "include/runner.h"} {
		path := filepath.Join(dir, rel)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("fixture\n"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func TestSnapshotContainsOnlyInputsAndCourseJudge(t *testing.T) {
	source := fixtureSource(t)
	for _, rel := range []string{"src/stale.o", "answers.md", "video.mp4", "langar", "test-results.txt"} {
		if err := os.WriteFile(filepath.Join(source, rel), []byte("excluded"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	archive := filepath.Join(t.TempDir(), "source.tar.gz")
	hash1, err := snapshot(source, archive)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(archive)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	names := map[string]bool{}
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		names[h.Name] = true
	}
	if len(names) != 8 || !names["course/sandbox.py"] || !names["course/probe.c"] || !names["course/test_langar.py"] || !names["q2/src/run.c"] {
		t.Fatalf("unexpected archive files: %v", names)
	}
	if err := os.WriteFile(filepath.Join(source, "src/run.c"), []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	hash2, err := snapshot(source, archive)
	if err != nil || hash1 == hash2 {
		t.Fatal("source change not reflected in hash", err)
	}
	copy := filepath.Join(t.TempDir(), "copy")
	if err := unpackSnapshot(archive, copy); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(copy, "q2/src/run.c"))
	if err != nil || string(data) != "changed" {
		t.Fatal("snapshot did not round-trip", err)
	}
}

func TestRejectSourceSymlink(t *testing.T) {
	source := fixtureSource(t)
	if err := os.Symlink(filepath.Join(source, "src/run.c"), filepath.Join(source, "src/link.c")); err != nil {
		t.Skip("symlinks unavailable:", err)
	}
	if _, err := sourceFiles(source); err == nil {
		t.Fatal("source symlink accepted")
	}
}

func TestRejectArchiveTraversal(t *testing.T) {
	archive := filepath.Join(t.TempDir(), "bad.tar.gz")
	f, _ := os.Create(archive)
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: "../outside", Mode: 0600, Size: 1}); err != nil {
		t.Fatal(err)
	}
	tw.Write([]byte("x"))
	tw.Close()
	gz.Close()
	f.Close()
	if err := unpackSnapshot(archive, t.TempDir()); err == nil {
		t.Fatal("archive traversal accepted")
	}
}

func TestRefuseExistingForeignInstance(t *testing.T) {
	a, fake, _ := appForTest("darwin")
	fake.Hook = func(_ string, args []string) (string, int, error) {
		if args[0] == "list" {
			return `{"list":[{"name":"foreign","state":"Running"}]}`, 0, nil
		}
		t.Fatalf("unexpected backend operation: %v", args)
		return "", 1, nil
	}
	_, err := a.ensureVM(context.Background(), options{State: t.TempDir(), Instance: "foreign", Timeout: time.Second})
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatal(err)
	}
}

func TestRefuseResetWhenOwnershipMismatches(t *testing.T) {
	a, fake, _ := appForTest("darwin")
	state := t.TempDir()
	writeJSON(filepath.Join(state, "vm.json"), vmConfig{Name: "course", Owner: "expected", Profile: Profile, Created: true})
	fake.Hook = func(_ string, args []string) (string, int, error) {
		if args[0] == "list" {
			return `{"list":[{"name":"course","state":"Running"}]}`, 0, nil
		}
		if args[0] == "exec" {
			return "foreign-owner", 0, nil
		}
		t.Fatalf("unsafe operation: %v", args)
		return "", 1, nil
	}
	if err := a.manage(context.Background(), "reset", options{State: state, Backend: "multipass"}); err == nil {
		t.Fatal("reset of foreign instance accepted")
	}
}

func passingReport() report {
	score, total := 100, 100
	r := report{Assignment: "hw2", Status: "passed", ExitCode: 0, Score: &score, Total: &total, Cleanup: "complete"}
	for i := 0; i < 15; i++ {
		points := 5
		if i == 0 {
			points = 15
		} else if i < 4 {
			points = 10
		}
		r.Results = append(r.Results, caseResult{ID: string(rune('a' + i)), Points: points, Earned: points, Passed: true})
	}
	return r
}

func TestRejectMisleadingScores(t *testing.T) {
	r := passingReport()
	if err := validateReport(r); err != nil {
		t.Fatal(err)
	}
	r.Status, r.ExitCode = "environment_error", 2
	if validateReport(r) == nil {
		t.Fatal("environment failure retained a functional score")
	}
	r = passingReport()
	r.Results[1].ID = r.Results[0].ID
	if validateReport(r) == nil {
		t.Fatal("duplicate case accepted")
	}
	r = passingReport()
	*r.Score = 5
	if validateReport(r) == nil {
		t.Fatal("inconsistent score accepted")
	}
}

func TestNativeFlowUsesSnapshotAndNeverMultipass(t *testing.T) {
	a, fake, _ := appForTest("linux")
	source, state := fixtureSource(t), t.TempDir()
	fake.Hook = func(name string, args []string) (string, int, error) {
		if name != "python3" {
			t.Fatalf("native backend called %s", name)
		}
		if args[0] == "-c" {
			return `{"system":"Linux"}`, 0, nil
		}
		work := args[2]
		if !strings.Contains(work, state) || strings.Contains(args[0], source) {
			t.Fatal("worker did not use a snapshot")
		}
		artifacts := filepath.Join(work, "artifacts")
		os.MkdirAll(artifacts, 0700)
		writeJSON(filepath.Join(artifacts, "report.json"), passingReport())
		return "test output\n", 0, nil
	}
	output := filepath.Join(t.TempDir(), "report.json")
	code := a.Run(context.Background(), []string{"test", "hw2", "--source", source, "--state-dir", state, "--json", output})
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	data, _ := os.ReadFile(output)
	var r report
	if err := json.Unmarshal(data, &r); err != nil || r.Status != "passed" || r.Backend != "native" || r.SourceHash == "" || r.WorkspaceCleanup != "complete" {
		t.Fatalf("invalid host report: %s (%v)", data, err)
	}
	if _, err := os.Stat(filepath.Join(source, "langar")); !os.IsNotExist(err) {
		t.Fatal("source directory changed")
	}
}

func TestStateLockExcludesParallelOperations(t *testing.T) {
	state := t.TempDir()
	unlocked, err := lock(state)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := lock(state); err == nil {
		t.Fatal("parallel operation acquired same lock")
	}
	unlocked()
	last, err := lock(state)
	if err != nil {
		t.Fatal(err)
	}
	last()
}

func TestCloudInitWarningsAreNotFatalErrors(t *testing.T) {
	for _, tc := range []struct {
		json string
		code int
		ok   bool
		warn bool
	}{
		{`{"status":"done","errors":[]}`, 0, true, false},
		{`{"status":"done","errors":[],"modules-final":{"errors":[]},"recoverable_errors":{"WARNING":["legacy schema"]}}`, 2, true, true},
		{`{"status":"done","errors":[],"modules-final":{"errors":["packages failed"]}}`, 2, false, false},
		{`{"status":"running","errors":[]}`, 0, false, false},
		{`{"status":"done","errors":[]}`, 1, false, false},
		{`not json`, 0, false, false},
	} {
		warning, err := cloudInitReady(tc.json, tc.code)
		if (err == nil) != tc.ok || warning != tc.warn {
			t.Fatalf("%s exit=%d warning=%v err=%v", tc.json, tc.code, warning, err)
		}
	}
}

func TestSetupCreatesOnlyAnOwnedInstance(t *testing.T) {
	a, fake, _ := appForTest("darwin")
	state := t.TempDir()
	created := false
	fake.Hook = func(_ string, args []string) (string, int, error) {
		switch args[0] {
		case "list":
			return `{"list":[{"name":"unrelated","state":"Running"}]}`, 0, nil
		case "launch":
			created = true
			if strings.Contains(strings.Join(args, " "), "unrelated") {
				t.Fatal("launch touched foreign instance")
			}
			return "", 0, nil
		case "exec":
			if args[1] != "owned-course" {
				t.Fatal("operation on foreign instance")
			}
			joined := strings.Join(args, " ")
			if strings.Contains(joined, "cloud-init status") {
				return `{"status":"done","errors":[]}`, 0, nil
			}
			if args[len(args)-1] == "/etc/langar-lab-owner" {
				cfg, _ := loadConfig(state)
				return cfg.Owner, 0, nil
			}
			if args[len(args)-1] == "/etc/langar-lab-profile" {
				return Profile, 0, nil
			}
			return "", 0, nil
		}
		t.Fatalf("unexpected operation: %v", args)
		return "", 1, nil
	}
	cfg, err := a.ensureVM(context.Background(), options{State: state, Instance: "owned-course", Timeout: time.Minute, CPUs: 2, Memory: "2G", Disk: "12G"})
	if err != nil || !created || !cfg.Created || !strings.HasPrefix(cfg.Owner, "lab-") {
		t.Fatalf("setup: %+v %v", cfg, err)
	}
	if strings.Contains(cloudInit(cfg), "permissions:") {
		t.Fatal("older Multipass converts permission strings to numeric YAML and causes schema warnings")
	}
}

func TestBuildFailureHasNoFunctionalScore(t *testing.T) {
	a, fake, _ := appForTest("linux")
	state, source := t.TempDir(), fixtureSource(t)
	fake.Hook = func(_ string, args []string) (string, int, error) {
		if args[0] == "-c" {
			return `{}`, 0, nil
		}
		r := report{Assignment: "hw2", Status: "build_failed", ExitCode: 3, Cleanup: "complete", Error: "compiler failed"}
		path := filepath.Join(args[2], "artifacts", "report.json")
		if err := writeJSON(path, r); err != nil {
			t.Fatal(err)
		}
		return "compiler error", 3, nil
	}
	output := filepath.Join(t.TempDir(), "result.json")
	if code := a.Run(context.Background(), []string{"test", "hw2", "--source", source, "--state-dir", state, "--json", output}); code != 3 {
		t.Fatalf("build failure exit %d", code)
	}
	data, _ := os.ReadFile(output)
	var r report
	json.Unmarshal(data, &r)
	if r.Score != nil || r.Total != nil || r.Status != "build_failed" || r.Profile != NativeProfile {
		t.Fatal("misleading build failure report", string(data))
	}
}

func TestSemesterAssignmentsSelectTheirWorkerAndJudge(t *testing.T) {
	for _, alias := range []string{"hw3", "hw04", "5", "hw6", "HW7", "hw8"} {
		t.Run(alias, func(t *testing.T) {
			a, fake, _ := appForTest("linux")
			source, state := fixtureSource(t), t.TempDir()
			expected := map[string]string{"hw3": "hw3", "hw04": "hw4", "5": "hw5", "hw6": "hw6", "HW7": "hw7", "hw8": "hw8"}[alias]
			fake.Hook = func(name string, args []string) (string, int, error) {
				if name != "python3" {
					t.Fatalf("native invoked %s", name)
				}
				if args[0] == "-c" {
					return `{}`, 0, nil
				}
				found := false
				for i := range args {
					if args[i] == "--assignment" && i+1 < len(args) && args[i+1] == expected {
						found = true
					}
				}
				if !found {
					t.Fatalf("assignment missing: %v", args)
				}
				r := report{Assignment: expected, Status: "build_failed", ExitCode: 3, Cleanup: "complete"}
				if err := writeJSON(filepath.Join(args[2], "artifacts", "report.json"), r); err != nil {
					t.Fatal(err)
				}
				return "", 3, nil
			}
			if code := a.Run(context.Background(), []string{"test", alias, "--source", source, "--state-dir", state}); code != 3 {
				t.Fatalf("exit %d", code)
			}
			entries, err := os.ReadDir(filepath.Join(state, "results", expected))
			if err != nil || len(entries) != 1 {
				t.Fatalf("assignment result path: %v", err)
			}
		})
	}
}

func TestSemesterSnapshotIncludesOfflineFixturesWithoutSolutions(t *testing.T) {
	source := fixtureSource(t)
	destination := filepath.Join(t.TempDir(), "snapshot.tar.gz")
	if _, err := snapshot(source, destination, "hw8"); err != nil {
		t.Fatal(err)
	}
	work := t.TempDir()
	if err := unpackSnapshot(destination, work); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"course/test_semester.py", "course/fixtures.py", "course/probe_runtime.c", "course/tools/make_rootfs.py"} {
		if _, err := os.Stat(filepath.Join(work, name)); err != nil {
			t.Fatal(name, err)
		}
	}
	if err := filepath.WalkDir(work, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		for _, bad := range []string{"run-answer", "Answers/", "private/"} {
			if strings.Contains(path, bad) {
				t.Fatalf("private file in snapshot: %s", path)
			}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}
