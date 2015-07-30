#!/usr/bin/python

import sys
import os
import argparse
import json
import os, errno
import xml.etree.cElementTree as ET


TESTSUITE="AutoMerge"
testSuite=ET.Element("testsuite", name=TESTSUITE, tests="0",errors="0", failures="0",skip="0")


REPO="git@git.soma.salesforce.com:pmantha/Integration.git"
REPO_DIR="Integration"

if os.environ.get("REPO","") != "":
    REPO=os.environ["REPO"]
    
if os.environ.get("REPO_DIR","") != "":
    REPO_DIR=os.environ["REPO_DIR"]

os.environ["REPO"] = REPO
os.environ["REPO_DIR"] = REPO_DIR

toolsDir=os.path.abspath(os.path.dirname(os.path.abspath(__file__))+"/..")
sys.path.append(toolsDir+"/config")
sys.path.append(toolsDir+"/automerge")
import automerge_core

validateScript=None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o","--validate-hook")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_true")

    args = parser.parse_args()

    if args.validate_hook:
        global validateScript
        validateScript = args.validate_hook
        automerge_core.beforePushValidateHook=beforePushValidateHook
        automerge_core.log("Using script %s for validation"%validateScript)
    if args.verbose:
        automerge_core.verbose = True

    automerge_core.reportMergeFailureFunc=reportMergeFailureLog
    automerge_core.reportSetupFunc=MergeJenkinsSetup
    automerge_core.reportAutoMergeResultsFunc=writeTestXml
    mkdir_p(toolsDir+"/tmp")
    os.chdir(toolsDir+"/tmp")
    automerge_core.tryFatal("rm -rf "+REPO_DIR)
    automerge_core.tryFatal("git clone %s %s"%(REPO, REPO_DIR))
    automerge_core.loadBranches("config/release-branches.json")
    return automerge_core.doAll(REPO_DIR)

def beforePushValidateHook():
    output, err = automerge_core.sh(validateScript)
    if err == 0:
        automerge_core.log("Passed validation on %s"%automerge_core.currentBranch())
        return True
    else:
        automerge_core.log("Validation failed %s"%automerge_core.currentBranch())
        automerge_core.log(output)
        return False

def MergeJenkinsSetup():
    testSuite.attrib["tests"] = str(int(testSuite.attrib["tests"]) + 1)
    testCase=ET.SubElement(testSuite, "testcase", classname=TESTSUITE, name="MergeJenkinsSetup")


def reportMergeFailureLog(*args):
    # GUS and PR goes here
    #log (args)    
    testSuite.attrib["failures"] = str(int(testSuite.attrib["failures"]) + 1)
    testSuite.attrib["tests"] = str(int(testSuite.attrib["tests"]) + 1)
    if args[0] == automerge_core.AutoMergeErrors.MergeError:
        testCase=ET.SubElement(testSuite, "testcase", classname=TESTSUITE, name="Merge%sTo%s"%(args[1],args[2]))
        failure=ET.SubElement(testCase, "failure", message="error")
        failure.text=args[3]
    elif args[0] == automerge_core.AutoMergeErrors.ValidateBranchError:
        testCase=ET.SubElement(testSuite, "testcase", classname=TESTSUITE, name="ValidateBranch%s"%(args[1]))
        failure=ET.SubElement(testCase, "failure", message="error")
        failure.text=args[2]            
    elif args[0] == automerge_core.AutoMergeErrors.PushValidationError:
        testCase=ET.SubElement(testSuite, "testcase", classname=TESTSUITE, name="PushBranchValidation%s"%(args[1]))
        failure=ET.SubElement(testCase, "failure", message="error")
        failure.text=args[2]   


def writeTestXml():
    testFile=os.getcwd() + "/AutoMergeResults_tests.xml"
    print "writing test xml file in dir: %s" % testFile
    tree=ET.ElementTree(testSuite)
    tree.write(testFile)    


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

exit(main())
