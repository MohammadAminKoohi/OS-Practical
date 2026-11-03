# Operating Systems Practical: Q2

Starter code, public judges and development tools for the course's second
practical question, **Langar**. The course handout defines each assignment's
requirements, deadlines and submission format.

## Langar

Langar is an incremental container runtime written in C. Each assignment adds
Linux operating-system features while you carry your own implementation forward:

- **HW2 — Processes:** fork, execute a command and wait for it.
- **HW3 — Namespaces:** isolate process IDs and the hostname.
- **HW4 — Resource controls:** set CPU affinity and an address-space limit.
- **HW5 — Mounts:** create private mounts and a matching `/proc` view.
- **HW6 — Root filesystem:** run a command inside a supplied root filesystem.
- **HW7 — Images:** combine local OCI image layers and image configuration.
- **HW8 — Process lifecycle:** supervise a workload, forward signals, reap
  children and clean up the runtime.

For example, Langar's command runner accepts a command and its arguments:

```sh
./q2/langar run -- /bin/echo hello
```

Each weekly handout specifies that release's supported behavior. Preserve your
working code from earlier assignments when merging the supplied updates.

## Repository layout

```text
.
├── README.md                 # Langar and repository overview
├── LANGAR-LAB.md             # Installation, usage and troubleshooting
├── JUDGE.md                  # Direct Linux judge commands
├── q2/
│   ├── Makefile              # Builds the C runtime
│   ├── include/runner.h      # Runtime interface
│   └── src/                  # Command parser, runtime and supplied helpers
├── judge/                    # Functional tests, probes and layout checker
└── tools/
    ├── install-langar-lab.sh # macOS/Linux helper installer
    ├── install-langar-lab.ps1# Windows PowerShell helper installer
    └── langar-lab/           # Helper source and checksums
```

The supplied files and test cases grow with each release. In HW2, implement
`q2/src/run.c`; `q2/src/main.c` provides the command-line parser.

## Getting started

```sh
git clone https://github.com/MohammadAminKoohi/OS-Practical.git
cd OS-Practical
```

Follow [LANGAR-LAB.md](LANGAR-LAB.md) to install the helper and prerequisites.
It runs on native Linux or in a local Ubuntu VM on macOS and Windows. To test
HW2 from the repository root on macOS/Linux:

```sh
sh tools/install-langar-lab.sh
./.langar-lab/bin/langar-lab setup
./.langar-lab/bin/langar-lab test hw2 --source ./q2 --json ./hw2-result.json
```

For direct builds and tests inside Linux, see [JUDGE.md](JUDGE.md).

## Testing and submission

The public functional judge reports a score out of 100. The unfinished HW2
starter builds and scores **5/100**; implementation work should raise that score.
Build and environment errors are reported separately and do not produce a
functional score. Local results help you debug; final grading reruns the course
judge on your submitted source.

Submit the required `q2/` files listed in the handout, with answers and video
under `q2/`. Remove executables and object files before submission. The layout
checker checks required files and basic formats; [JUDGE.md](JUDGE.md) explains
how to run it and save judge logs.
