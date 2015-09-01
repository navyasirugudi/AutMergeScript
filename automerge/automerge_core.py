import os
import subprocess
from subprocess import Popen, PIPE
from os import path,getcwd,chdir
import pdb
import re
import uuid
import fileinput

import json
# Const
NO_MERGE="@no-merge@"


toolsDir = path.abspath(path.dirname(__file__)+"/..")
REL_BRANCH=["master"]


commitMessages = []
def getMergeCommitMessages():
    return commitMessages

# Python 2.7 Enum type
class AutoMergeErrors:
    ValidateBranchError,MergeError,PushValidationError = range(3)


def loadBranches(configFile):
    f = open(toolsDir+"/"+configFile, "r")
    branchDef = json.load(f)
    global REL_BRANCH
    REL_BRANCH=branchDef["release-branches"]

verbose=False
beforePushTestHook = None
beforePushValidateHook = None
reportMergeFailureFunc=None
reportSetupFunc=None
reportAutoMergeResultsFunc=None
reportMergeSuccessFunc=None


def doAll(repoDir):
    errMsg = ""
    rc = 0
    global commitMessages
    commitMessages = []

    if repoDir:
        chdir(repoDir)

    reportSetup()
    log ("Current working directory is %s"%path.abspath(getcwd()) )
    tryFatal("git fetch")
    fetchSubmodules()

    for i in range(len(REL_BRANCH)) :
        br=branch(i)
        if br == 'master':
            rc = 0
            break # We reached end of list

        next=branch(i+1)

        if validateBranchList(br, next) > 0:
            errMsg = "Failed branch validation"
            log(errMsg)
            continue

        if not checkMerged (br,next) :
            if not autoMerge(br, next):
                errMsg = "Unable to finish automerge between %s and %s"%(br,next)
                log (errMsg)
                rc = 1
                break
                if i < len(REL_BRANCH) - 2:
                    resetbrToRemote(next) #this is for further merges to continue
            else:
                log ("Merge %s to %s: success"%(br,next))
                reportMergeSuccess(br,next,"")
        else:
            log ("Merge %s to %s: not needed"%(br,next))
            reportMergeSuccess(br,next,"(not needed)")

    reportAutoMergeResults()
    return rc, errMsg

def fetchSubmodules():
    repo = os.environ["REPO"]
    if "insights" in repo:
        return

    pointGitModulesToFork()

    submodules = getSubModules()
    for sm in submodules:
        path = sm["path"]
        pwd = currentPath()
        chdir(path)
        fetchSubmodules()
        chdir(pwd)

def pointGitModulesToFork():
    if (not os.path.isfile(".gitmodules")):
        return ""

    log("Pointing gitmodules to fork")
    forkRepoRegex = "git@github.com:(.*)/(.*)"
    forkRepoC = re.compile(forkRepoRegex)
    fmatch = forkRepoC.match(os.environ['REPO'])

    if (fmatch is not None and len(fmatch.groups()) > 0):
        forkName = fmatch.groups()[0]
        for line in fileinput.input('.gitmodules', inplace=True):
            print(line.replace('insights', forkName))

        # sh("sed -i='' 's/insights/%s/g' .gitmodules"%forkName)
        tryFatal("git submodule update --init")
        tryFatal("git checkout .gitmodules")


#this resets the given branch and its submodules to where they were on the remote.
def resetbrToRemote(br):
    abortMerge() #erases anyconflicts on the branch due to previous merge

    tryFatal1("git checkout %s"%br)
    sha = tryFatal1("git rev-parse origin/%s"%br)

    tryFatal("git reset --hard %s"%sha) #set back to where the remote was
    tryFatal("git submodule update")

def abortMerge():
    output, err = sh("git ls-files -u") #check if there are unmerged files
    if err == 0 and len(output) > 0:
        tryFatal("git reset --merge")

    submodules = getSubModules()

    for subModule in submodules:
        currPwd = currentPath()
        chdir(subModule["path"])

        abortMerge()
        chdir(currPwd)

def reportMergeFailure(*args):
    if reportMergeFailureFunc:
        reportMergeFailureFunc(*args)
    else:
        log ("Merge failure: %s"%[x for x in args])

def reportMergeSuccess(*args):
    if reportMergeSuccessFunc:
        reportMergeSuccessFunc(*args)
    else:
        log ("Merge success: %s"%[x for x in args])

def reportSetup():
    if reportSetupFunc:
        reportSetupFunc()
    else:
        log ("Default report setup not set.")

def reportAutoMergeResults():
    if reportAutoMergeResultsFunc:
        reportAutoMergeResultsFunc()
    else:
        log ("Nothing to report")


def sh(cmd):
    if verbose:
        print cmd

    proc = Popen(cmd + " 2>&1",  shell=True, stdout=PIPE, stderr=PIPE)
    output, err = proc.communicate()
    if verbose:
        print output
    return (output, proc.poll())


def tryFatal(cmd):
    output, retcode = sh(cmd)
    if retcode:
        log ("%s\n%s"%(cmd, output))
        raise subprocess.CalledProcessError(retcode, cmd, output=output)
    return output

# Same as tryFatal by returns only first line in the output
def tryFatal1(cmd):
    output = breakStripStr(tryFatal(cmd))
    if len(output)>0:
            return output[0]

    return ""

def log (message):
   print "AUTOMERGE: %s" % message

# Split text into array of lines, strip all blanks from each line and return non-empty
def breakStripStr(output):
    # split the output
    outList = output.split("\n")
    # for each non empty line strip the spaces
    return [i.strip() for i in outList if i.strip()]

# Checks if barcnh $1 is merged into branch $2
# return True if not merged False otherwise
def checkMerged(mergeFrom, mergeTo):
    log ("check if branch %s merged into %s" %(mergeFrom, mergeTo))
    merged=breakStripStr(tryFatal("git branch -a --merged remotes/origin/%s"%mergeTo)) # || echo "remotes/origin/$mergeFrom")

    if "remotes/origin/%s"%mergeFrom in merged:
        log ("%s to %s: OK"%(mergeFrom, mergeTo))
        return True

    log ("%s is not merged to %s!"%(mergeFrom, mergeTo))
    return False


def branch(idx):
    return REL_BRANCH[idx]

def rbranch(idx):
    return "remotes/origin/%s"%branch(idx)

def validateBranchList(src, target):
    log("Validating required branches for merge from %s to %s"%(src, target))
    result=0

    for br in [src, target]:
        if not branchExists(br):
            result=result+1
            errMsg = "Missing branch %s"%br
            log (errMsg)
            reportMergeFailure(AutoMergeErrors.ValidateBranchError, getRepoName(), src, target, errMsg)
            continue

    if (result == 0):
        ok = validateSubModulesForMerge(src, target)
        if not ok:
           result=result+1

    if (result == 0):
        log("Branch validation successful between %s to %s"%(src, target))

    return result

def validateSubModulesForMerge(srcbranch, target):
    submodules = getSubModules()
    reponame = getRepoName()
    allok = True

    for submodule in submodules:
        if submMergeRequired(srcbranch, target, submodule):
            #check submodule pointer points to the head of the corresponding release branch of the submodules on both src and target branches.
            srcOk, msg = sanityCheckSubmForMerge(reponame, srcbranch, submodule)

            if (not srcOk):
                allok = False
                log (msg)
                reportMergeFailure(AutoMergeErrors.ValidateBranchError, submodule["name"], srcbranch, target, msg)

            targetOk, msg = sanityCheckSubmForMerge(reponame, target, submodule)

            if (not targetOk):
                allok = False
                log (msg)
                reportMergeFailure(AutoMergeErrors.ValidateBranchError, submodule["name"], srcbranch, target, msg)

    return allok

def submMergeRequired(srcbranch, target, submodule):

    targetSubSha = getShaOfSubModule(target, submodule["path"])
    srcSubSha = getShaOfSubModule(srcbranch, submodule["path"])

    if (srcSubSha != targetSubSha):
        curpath = currentPath()
        chdir(submodule["path"])

        revList=breakStripStr(tryFatal("git log --pretty=%%H %s..%s"%(targetSubSha,srcSubSha)))

        chdir(curpath)

        if len(revList) > 0:
            return True

    return False

def sanityCheckSubmForMerge(mainRepoName, repoBranch, submodule):
    if repoBranch == "master": #ignoring sanity check for master submodule branch. Just merge to master and update submodule pointers
        return True, ""

    subBranch = getNamingConvention(mainRepoName, repoBranch)
    submSha = getShaOfSubModule(repoBranch, submodule["path"])
    brHead = subMbranchHead(submodule["path"], subBranch)

    if not brHead:
        return False, "Src branch has submodule changes in %s that need to be integrated. Expected branch %s doesn't exist for the submodule: %s in path: %s"%(submodule["name"], subBranch, submodule["name"], submodule["path"])

    if submSha != brHead:
        return False, "%s's submodule \"%s\" on %s is not pointing to the head of submodule's release branch %s"%(mainRepoName, submodule["name"], repoBranch, subBranch)

    return True, ""

def currentBranch():
    return tryFatal1("git rev-parse --abbrev-ref HEAD")

def currentPath():
    return tryFatal1("pwd")

dryRun=0 # if set to 1 then, don't actually merge
# $1 - branch to merge into current
# Take care of @no-merge@ here. changes that come from any branch that has @no-merge@ in it's name or @no-merge@ in any commit
# must be skipped but marked merged.
# In case of conflict or other error do all GUS/GitHub business
# return 0 if merge succesfull
# return 1 if merge failed and reporting suceeded
# exit with code 1 if reporting failed (someone must review Jenkins job)
# Both branches must be checked out and in sync with remote before calling
def doMerge(branch):
    target= currentBranch()

    #First, merge submodules if need be
    mergeDone, submChangeExists = mergeSubModules(branch, target)
    if not mergeDone:
        return False

    if submChangeExists:
        err = updateSubmodulePointers(target)
        if err != 0:
            message = "Unable to update submodule pointers to appropriate branches in target branch %s"%target
            log(message)
            reportMergeFailure(AutoMergeErrors.MergeError, getRepoName(), branch, target, message)
            return False

    global commitMessages

    # Determine all merges that occurred to target since branch deviated from it
    revList=breakStripStr(tryFatal("git log --merges --pretty=%%H %s..%s"%(target,branch)))
    log ("Merge commits: %s"%revList)

    # Walk throuh the list in reverse order
    for idx in reversed(range(len(revList))) :
        s=revList[idx]
        # Merges can be on either branches. So pick only those that are not in target
        branches=breakStripStr(tryFatal("git branch --contains %s"%s))
        merged=False
        for br in branches:
            log ("Check %s against %s"%(br,target))
            if br == target:
                merged=True
                break

        if not merged :
            #commit $s  is not in $target. So it's merge candidate.

            sha=tryFatal1("git show --format=%%H -s %s"%s)
            commitMessage=tryFatal1("git show --format=%%s -s %s"%s)
            commitDetails=tryFatal1("git show --format=\"%%cd %%h %%s\" --date=iso -s %s"%s)
            log ("Merging %s to %s [ %s ]"%(branch,target,commitDetails))

            if NO_MERGE in commitMessage:
                # No merge commit. Merge it with -s ours flag
                # This should not fail because of conflict
                lCommitMsg = '\"Auto merge (Skip) from %s->%s: %s\" %s' % (branch, target, commitMessage, sha)
                tryFatal("git merge --no-ff -s ours -m %s"%(lCommitMsg))
                commitMessages.append(lCommitMsg)
                log ("@no-merge@ merging %s"%commitDetails)
            else:
                lCommitMsg = '\"Auto merge (Regular) from %s->%s: %s\" %s' % (branch, target, commitMessage, sha)
                mergeResult, err=sh("git merge --no-ff -m %s"%(lCommitMsg))

                if  err != 0:
                    log ("Conflict merging %s"%commitDetails)
                    reportMergeFailure(AutoMergeErrors.MergeError, getRepoName(), branch, target, mergeResult)
                    return False
                commitMessages.append(lCommitMsg)
                log ("Succesfully merged %s"%commitDetails)


    log("All merge commits (if any) are now in target branch %s. Validating that branches %s and %s are completely merged."%(target, branch, target))
    # Test that we are fully merged

    tryFatal1("git checkout %s"%target)
    sha=tryFatal1("git show -s --pretty=%h HEAD")

    #this test will only validate if there are any direct commits after the last merge.
    output, err = sh("git merge --no-ff -m \"Test Merge\" %s"%branch)
    if err == 0:
        shaNew=tryFatal1("git show -s --pretty=%h HEAD")
    else:
        shaNew="0"
        log (output)

    if sha != shaNew:
        message="Branch %s is not fully merged into %s after merging all pull request \
merges. Do you have commits without PR? Manual intevention is required."%(branch, target)
        log(message)
        reportMergeFailure(AutoMergeErrors.MergeError, getRepoName(), branch, target, message)
        return False

    return True

def updateSubmodulePointers(target):
    gotoBrAndSubmUpdate(target)

    submodules = getSubModules()
    if (len(submodules) == 0):
        return 0

    curPath = currentPath()
    reponame = getRepoName()
    update = False

    for submodule in submodules:
        brName = getNamingConvention(reponame, target)
        submodulePath = submodule["path"]
        chdir(submodulePath)

        if branchExists(brName): #The validation would have been done earlier. Branch not existing here just means it was not needed to be created
            currSubmPointer = tryFatal1("git show --format='%H'")

            tryFatal("git checkout %s"%brName)
            brHead = tryFatal1("git show --format='%H'")

            if currSubmPointer != brHead:
                update = True

        chdir(curPath)

    if update:
        msg = "Updating submodule pointers of %s to their corresponding release-branches"%target
        log(msg)
        updatebr = "submUpdate-on-%s-%s"%(target, str(uuid.uuid4()))

        tryFatal("git checkout -b %s"%updatebr)
        tryFatal("git status")
        tryFatal("git commit -a -m \"%s\""%msg)

        gotoBrAndSubmUpdate(target)
        output, err = sh("git merge --no-ff -m \"Auto merge: %s\" %s"%(msg,updatebr))
        if err != 0:
            log(output)
            return err

    return 0

def gotoBrAndSubmUpdate(br):
    tryFatal("git checkout %s"%br)
    tryFatal("git submodule update")

def getSubModules():
    if (not os.path.isfile(".gitmodules")):
        print "no submodules"
        return []

    gitmfile = open(".gitmodules", "r")
    modules = []

    urlregex = "(.*)url(.*)=(.*)git@github.com:(.*)/(.*)"
    pathregex = "(.*)path(.*)=(.*)"

    module = {}
    for line in gitmfile:
        print "Recieved %s"%(line.strip())
        if len(line) == 0:
            continue
        
        if "url" in line:
            print "found url in line"
            print "xx %s"%(line.split("/")[1].strip())
            module["name"] = line.split("/")[1].strip()
            print module
            
        if "path" in line:
            print "found path in line"
            print "ss %s"%(line.split("path = ")[1].strip())
            module["path"] = line.split("path =")[1].strip()
            print module

        if ("path" in module and "name" in module):
            print module
            modules.append(module)
            module = {}

    return modules

#gets the sha of the head of the submodule's branch
def getHead(branch, submodule):
    curPath = currentPath()

    tryFatal("git submodule update")

    chdir(submodule)
    tryFatal("git checkout %s"%branch)

    sha = tryFatal1("git show --format='%H'")

    chdir(curPath)
    tryFatal("git submodule update")

    return sha

#gets the sha of the head of the submodule in the parent branch
def getShaOfSubModule(parentbranch, submodulepath):
    curPath = currentPath()

    gotoBrAndSubmUpdate(parentbranch)

    chdir(submodulepath)

    sha = tryFatal1("git show --format='%H'")

    chdir(curPath)

    return sha

def getNamingConvention(reponame, branch):
    if branch == "master":
        return "master"

    return reponame + "_" + branch

def getRepoName():
    name = tryFatal1("basename $(git remote show -n origin | grep Fetch | cut -d: -f2-)")
    return name.replace('.git','')

def mergeSubModules(srcbranch, target):
    submodules = getSubModules()
    reponame = getRepoName()
    currPath = currentPath()
    submChangeExists = False

    for submodule in submodules:
        #check submodule pointer to head of the corresponding release branch of the submodules on both src and target branches.
        if not submMergeRequired(srcbranch, target, submodule):
            continue

        submChangeExists = True
        chdir(submodule["path"])

        srcsubmBr = getNamingConvention(reponame, srcbranch)
        targetsubmBr = getNamingConvention(reponame, target)
        merged = autoMerge(srcsubmBr, targetsubmBr) #Will parent be a submodule of the submodule again? Then this would become a circular loop. So far we have only one level on submodules

        chdir(currPath)

        if not merged:
            log("Failed merging submodule: %s on %s"%(submodule["name"], reponame))
            return False, submChangeExists

        log("AutoMerge succeeded for %s"%submodule)

    return True, submChangeExists

def branchExists(branchName):
    tryFatal("pwd")
    sha, err = sh("git rev-parse --quiet --verify remotes/origin/%s"%branchName)
    return err == 0

def subMbranchHead(submodulePath, branchName):
    currPwd = currentPath()
    chdir(submodulePath)
    exists = branchExists(branchName)
    headOfBranch = ""

    if exists:
        tryFatal("git checkout %s"%branchName)
        headOfBranch = tryFatal1("git show --format='%H'")

    chdir(currPwd)

    return headOfBranch

# Push data to origin. In case of failure, attempt to pull latest version and retry up to 5 times
def pushChanges(old) :
    if not beforePushTestHook is None:
        beforePushTestHook()

    pushResult=""
    cb = currentBranch()

    pushargs = ""
    if dryRun:
        pushargs = "--dry-run"

    for i in range(5):
        if not beforePushValidateHook is None:
            log("Start validation before push in %s"%cb)
            if not beforePushValidateHook():
                errMsg = "Validation before push in %s failed"%cb
                log (errMsg)
                reportMergeFailure(AutoMergeErrors.PushValidationError, getRepoName(), old, cb, errMsg)
                return False

        pushResult,err =sh("git push %s"%pushargs)
        if err != 0: # todo: check rejected?
            # push failed - typically because target moved forward and push is rejected
            tryFatal("git reset --hard HEAD^") # Undo merge
            tryFatal("git pull") # Update from origin
            # try again

            if not doMerge(old):
                return False

            continue # Merge succeeded retry push

        return True # done

    log ("Can't push after few tries. Last push error:\n%s\n"%pushResult)
    return False

# Attempt automatically merge branch $1 to branch $2
# If return is 1 then further merging must be aborted
def autoMerge(old, new):
    log ("Trying automerge %s to %s"%(old,new))

    # Following commands should not normally fail.
    tryFatal("git checkout %s"%old)
    tryFatal("git pull")
    tryFatal("git checkout %s"%new)
    tryFatal("git pull")

    # Fail in merge requires a ticket and PR
    if not doMerge(old):
        return False

    return pushChangesFunc(old)

pushChangesFunc=pushChanges
