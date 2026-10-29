"""Supplied Linux lab runner. Results are observations, not assignment grades."""
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

class EnvironmentError(RuntimeError):
    pass

class Lab:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.observations = []
    def need(self, *programs):
        missing = [x for x in programs if not shutil.which(x)]
        if missing:
            raise EnvironmentError('Missing tools: '+', '.join(missing)+'. See the handout package list; run inside Linux or the course VM.')
    def run(self, command, *, privileged=False, expected=(0,), timeout=20):
        command = [str(x) for x in command]
        if privileged and os.geteuid() != 0:
            self.need('sudo')
            command = ['sudo', '-n', *command]
        print('$ '+shlex.join(command), flush=True)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            out, err = process.communicate(timeout=timeout)
        finally:
            # Kill only this runner's process group, including a timed-out tracer.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    subprocess.run(['sudo','-n','/bin/kill','-'+str(int(sig)),
                                    '--','-'+str(process.pid)],capture_output=True,timeout=5)
            process.wait()
        output, error = out.decode(errors='replace'), err.decode(errors='replace')
        print(output, end='' if output.endswith('\n') or not output else '\n', flush=True)
        if error:
            print(error, end='' if error.endswith('\n') else '\n', file=sys.stderr, flush=True)
        self.observations.append(dict(command=command,exit_code=process.returncode,stdout=output,stderr=error))
        if process.returncode not in expected:
            raise EnvironmentError(f'Command failed ({process.returncode}); check the displayed error. No Q3 score was assigned.')
        return output
    def compile(self, filename, output):
        self.need('gcc')
        dest = self.directory / output
        self.run(['gcc','-std=c11','-D_GNU_SOURCE','-O2','-Wall','-Wextra','-Werror',
                  str(Path(__file__).parent / filename),'-o',dest])
        return dest

def main(hw, experiment):
    import argparse
    p=argparse.ArgumentParser(description='Run the supplied HW'+str(hw)+' Q3 observation inside Linux; interpretation is manually graded.')
    p.add_argument('--json',type=Path,help='optional observation record (not a grade)')
    a=p.parse_args()
    report=dict(assignment=f'hw{hw}-q3',score=None,evaluation='manual',status='environment_error',
                environment=dict(system=platform.system(),kernel=platform.release(),architecture=platform.machine()),observations=[])
    code=2
    def interrupted(_sig,_frame):
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if sys.platform!='linux':
            raise EnvironmentError('Linux kernel required. On macOS/Windows use langar-lab shell --backend multipass and run the released tools there.')
        with tempfile.TemporaryDirectory(prefix=f'langar-q3-hw{hw}-') as directory:
            lab=Lab(directory)
            try:
                report['measurements']=experiment(lab)
            finally:
                report['observations']=lab.observations
        report['status']='completed';code=0
        print('Observation complete. Answer the report/video questions; no automatic Q3 grade was assigned.')
    except KeyboardInterrupt:
        report.update(status='interrupted',error='Observation interrupted');code=130
    except (OSError,EnvironmentError,subprocess.SubprocessError,ValueError) as exc:
        report['error']=str(exc);print(str(exc),file=sys.stderr)
    finally:
        if a.json:
            a.json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return code
