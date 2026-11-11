# Running the HW2 judge

Install Langar Lab with [LANGAR-LAB.md](LANGAR-LAB.md), then run:

```sh
./.langar-lab/bin/langar-lab setup
./.langar-lab/bin/langar-lab test hw2 --source ./q2 --json result.json
```

On native Linux, install GCC, Make, Python 3.10+, Bubblewrap and sudo, then
run `sudo -v` before using the helper. Builds and commands run in separate
sandboxes as unprivileged host UID 65534; trusted judge files stay outside.
Windows/macOS use the course Multipass VM. See the helper guide for PowerShell.

Directly in Linux:

```sh
make -C q2 clean
make -C q2 CC=gcc
sudo python3 judge/hw2.py --binary ./q2/langar --json result.json
python3 judge/check_submission.py ./submission
```

The 15 public cases total 100 points and print their individual weights.
Exit codes: 0 passed, 1 functional failure, 2 environment/setup error.
The helper also uses 3 for build failure and 130 for interruption.
Submit the required source, answers, video and test log under `q2/`.
The course handout defines the assignment; this repository contains Q2 tools only.
