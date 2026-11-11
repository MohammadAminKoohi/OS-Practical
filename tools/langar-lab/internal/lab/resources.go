package lab

import "embed"

const Version = "0.3.0"
const Profile = "ubuntu24.04-hw2-v1"
const NativeProfile = "native-linux-hw2-v1"
const JudgeVersion = "hw02-v1.1.0"

//go:embed resources/agent.py resources/sandbox.py resources/hw2/test_langar.py resources/hw2/probe.c resources/semester
var resources embed.FS

var CaseCounts = map[string]int{"hw2": 15, "hw3": 7, "hw4": 6, "hw5": 5, "hw6": 7, "hw7": 6, "hw8": 7}

func judgeVersion(assignment string) string {
	if assignment == "hw2" {
		return JudgeVersion
	}
	return "hw0" + assignment[2:] + "-v1.1.0"
}
