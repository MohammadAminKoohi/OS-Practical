# Langar Lab

Langar Lab builds your C code in Linux and runs the **Q2 public tests**.
**Linux** defaults to native execution, with no VM download. **macOS and
Windows** use a local Ubuntu VM managed by Multipass and reused between runs.
Assignment requirements and submission rules remain in the course handout.
For the direct HW2 judge, see [JUDGE.md](JUDGE.md).

## 1. Install prerequisites

- **Linux native:** GCC, Make and Python 3.10+. On Ubuntu/Debian:

  ```sh
  sudo apt update
  sudo apt install build-essential python3 busybox-static util-linux procps sudo curl ca-certificates git
  ```

  Later namespace/mount tests also need sudo privileges.
- **macOS/Windows:** follow the [official Multipass installation guide](https://canonical.com/multipass/docs/latest/how-to-guides/install-multipass/),
  including its OS and virtualization requirements. Open a new terminal and
  check `multipass version`. The VM receives the compiler and Python; you do
  not need host Go, Python, Bash or Docker to run the executable. The Unix
  installer uses `sh` and `curl`; the Windows installer uses PowerShell.

Clone this repository with Git, or use **Code → Download ZIP** and extract it.
Run the following commands from the `OS-Practical` directory.

## 2. Install and run

macOS/Linux:

```sh
sh tools/install-langar-lab.sh
./.langar-lab/bin/langar-lab doctor
./.langar-lab/bin/langar-lab setup
./.langar-lab/bin/langar-lab test hw2 --source ./q2 --json ./hw2-result.json
```

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install-langar-lab.ps1
.\.langar-lab\bin\langar-lab.exe doctor
.\.langar-lab\bin\langar-lab.exe setup
.\.langar-lab\bin\langar-lab.exe test hw2 --source .\q2 --json .\hw2-result.json
```

The execution-policy option applies only to that installer process. Installers
detect amd64/arm64, download only your executable from
[Langar Lab v0.2.0](https://github.com/MohammadAminKoohi/OS-Practical/releases/tag/langar-lab-v0.2.0),
and verify it against the repository's SHA-256 checksums before running it.
Installation is local to `.langar-lab/bin/`; no administrator access or PATH
change is needed. Rerun the installer to retry or install the version pinned by
your repository checkout; this preserves VMs and reports.

The first VM setup needs internet to download Ubuntu 24.04 and packages.
Defaults are 2 CPUs, 2 GB RAM and a 12 GB virtual disk. Native setup only checks
your installed tools. After editing code, repeat just the `test` command.
`--source` must name the directory containing `Makefile`, `src/` and `include/`;
quote paths containing spaces. The unfinished HW2 starter scoring **5/100** is
expected. Use `hw3` through `hw8` as each assignment is released, continuing your
own earlier code. The helper contains no reference solution.

## 3. Choose native Linux or a VM

These examples use the Unix executable path; use the `.exe` path on Windows.

```sh
./.langar-lab/bin/langar-lab test hw2 --source ./q2 --backend native
./.langar-lab/bin/langar-lab setup --backend multipass
./.langar-lab/bin/langar-lab test hw2 --source ./q2 --backend multipass
```

Native works only on Linux. Linux users can also install Multipass and select
it explicitly. HW3–HW8 compile as your regular user and run privileged judges
through `sudo -n`. On native Linux, run `sudo -v` in the same terminal first;
if your sudo policy cannot authorize the worker, choose Multipass or the direct
judge documented for that release. Run the CLI as your regular user.

## 4. Read results and resolve common problems

Each case prints its result and points. The printed results directory contains
`report.json`, build/test logs and raw judge JSON when produced. `--json` saves
an extra report at your chosen path. Exit codes are:

- `0`: all tests passed.
- `1`: tests completed with failing cases.
- `2`: usage, dependency, environment or VM transport error; no score.
- `3`: build failed or timed out; no score. Read `build.log`.
- `130`: interrupted with Ctrl-C; no score.

If Multipass is unavailable, check installation, its running service and
`multipass version`. For slow setup, use `setup --timeout 20m`; for a longer test,
use `test hw2 --source ./q2 --timeout 4m`. A checksum mismatch prevents
installation: obtain the checkout and installer for the same release again.
Local scores are feedback; final grading reruns the course-owned judge on your
submission.

## 5. How it works

1. Copies `Makefile`, `src/` and `include/` into a source snapshot. Your original
   files stay unchanged; host executables and object files are not used. Source
   symlinks are rejected, so copy actual files into the required layout.
2. Builds the copy with Make/GCC inside Linux and runs its embedded public
   judge. Code is processed locally: Multipass transfers it to your own local
   VM, with no upload to GitHub or a university grading service.
3. Saves case results, source hash and actual Linux environment details. Host
   reports remain under the user-cache directory in `langar-lab`, at the path
   printed after each run. Temporary Linux build workspaces are cleaned up.

## 6. VM commands

```sh
./.langar-lab/bin/langar-lab status --backend multipass
./.langar-lab/bin/langar-lab shell --backend multipass
./.langar-lab/bin/langar-lab stop --backend multipass
```

Use `exit` to leave the guest shell. The helper manages only its own course VM.
`reset --backend multipass` deletes and recreates that VM, including files you
saved manually inside it; host code and reports remain. Add `--keep-work` to a
test to retain its Linux copy for debugging; the workspace path is printed.

## Optional: manual download or build from source

Executables and `SHA256SUMS` are on the
[release page](https://github.com/MohammadAminKoohi/OS-Practical/releases/tag/langar-lab-v0.2.0).
Use `darwin` for macOS, `linux` for Linux and `windows` for Windows; use `amd64`
for Intel/AMD 64-bit and `arm64` for Apple Silicon/ARM64. Verify SHA-256 before
running. On Unix, run `chmod +x FILE`. Binaries are unsigned; if your OS blocks
execution, building from source is an alternative.

With [Go 1.22+](https://go.dev/doc/install), no third-party Go modules are needed.
Run inside `tools/langar-lab/` (the Windows output uses `.exe`):

```sh
go test ./...
go build -trimpath -o dist/langar-lab ./cmd/langar-lab
```

On Windows use `-o dist/langar-lab.exe`. With Python 3 installed,
`python3 scripts/build.py` cross-builds all six targets and generates checksums.
Build output goes in `dist/`; it is not part of your assignment submission.
Cross-building does not imply runtime testing on every host.
