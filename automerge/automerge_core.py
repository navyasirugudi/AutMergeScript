import os
import subprocess
from subprocess import Popen, PIPE
from os import path,getcwd,chdir
import pdb
import re

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


def doAll(repoDir):
    errMsg = ""
    rc = 0
    global commitMessages
    commitMessages = []

    if repoDir:
        print "Changing directory"
        chdir(repoDir)

    reportSetup()
    log ("Current working directory is %s"%path.abspath(getcwd()) )
    tryFatal("git fetch")
    tryFatal("git submodule update --init --recursive")

    if validateBranchList() > 0:
        errMsg = "Failed branch validation"
        log (errMsg)
        rc = 1

    if errMsg == "":
        for i in range(len(REL_BRANCH)) :
            br=branch(i)
            if br == 'master':
                rc = 0
                break # We reached end of list

            next=branch(i+1)

            if not checkMerged (br,next) :
                if not autoMerge(br, next):
                    errMsg = "Unable to finish automerge. Everything must be reported by now."
                    log (errMsg)
                    rc = 0 # We exit with success here since we expect everything reported so Jenkins must report success
                    break

    reportAutoMergeResults()
    return rc, errMsg


def reportMergeFailure(*args):
    if reportMergeFailureFunc:
        reportMergeFailureFunc(*args)
    else:
        log ("Merge failure: %s"%[x for x in args])

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
    print cmd
    if verbose:
        print cmd

    proc = Popen(cmd + " 2>&1",  shell=True, stdout=PIPE, stderr=PIPE)
    output, err = proc.communicate()
    if verbose:
        print output
    print output
    return (output, proc.poll())


def tryFatal(cmd):
    print cmd
    output, retcode = sh(cmd)
    if retcode:
        log ("%s\n%s"%(cmd, output))
        raise subprocess.CalledProcessError(retcode, cmd, output=output)
    print output
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


# def validateBranchList():
#     result=0

#     for i in range(len(REL_BRANCH)) :
#         br=rbranch(i)
#         sha, err = sh("git rev-parse --quiet --verify %s"%br)
#         if err != 0 :
#            result=result+1
#            errMsg = "Missing branch %s"%br
#            log (errMsg)
#            reportMergeFailure(AutoMergeErrors.ValidateBranchError, REL_BRANCH[i].strip(), errMsg)

#     return result

# def validateBranchList():
#     submodules = getSubModules()
#     for i in range(len(REL_BRANCH)):
#         for submodule in submodules:
#             print getShaOfSubModule(branch(i), submodule["path"])

def validateBranchList():
    result=0

    for i in range(len(REL_BRANCH)) :
        br=rbranch(i)
        sha, err = sh("git rev-parse --quiet --verify %s"%br)
        if err != 0 :
           result=result+1
           errMsg = "Missing branch %s"%br
           log (errMsg)
           reportMergeFailure(AutoMergeErrors.ValidateBranchError, REL_BRANCH[i].strip(), errMsg)
           continue

        #if err is 0 check submodules
        if (i == 0):
            continue

        branch1 = rbranch(i-1)
        branch2 = rbranch(i)

        if (branchExists(rbranch(i - 1)) and branchExists(rbranch(i))):
            ok = validateSubModulesForMerge(branch(i - 1), branch(i))
            if not ok:
               result=result+1

    return result

def validateSubModulesForMerge(srcbranch, target):
    print "Validating submodules for merge between %s and %s"%(srcbranch, target)
    submodules = getSubModules()
    reponame = getRepoName()
    msg = ""
    allok = True

    for submodule in submodules:
        print "Validate submodule %s:%s"%(submodule["path"], submodule["name"])
        #check submodule pointer to head of the corresponding release branch of the submodules on both src and target branches.
        targetBrSubModuleSha = getShaOfSubModule(target, submodule["path"])
        #print "Current branch %s"%currentBranch()
        #print targetBrSubModuleSha
        srcBrSubModuleSha = getShaOfSubModule(srcbranch, submodule["path"])
        #print "Current branch %s"%currentBranch()
        #print srcBrSubModuleSha

        if (srcBrSubModuleSha == targetBrSubModuleSha): #merge not required
            continue

        srcOk, msg = validateSubModule(reponame, srcbranch, submodule, srcBrSubModuleSha)

        if (not srcOk):
            allok = False
            log (msg)
            reportMergeFailure(AutoMergeErrors.ValidateBranchError, "%s:%s"%(srcbranch.strip(),submodule["path"]), msg)

        targetOk, msg = validateSubModule(reponame, target, submodule, targetBrSubModuleSha)

        if (not targetOk):
            allok = False
            log (msg)
            reportMergeFailure(AutoMergeErrors.ValidateBranchError, "%s:%s"%(target.strip(),submodule["path"]), msg)

        #if not autoMerge(subMSrcBrName, subMTargetBrName): #Will parent be a submodule of the submodule again? Then this would become a circular loop. So far we have only one level on submodules
         #   return False, "Failed merging submodule: %s on %s"%(submodule["name"], reponame)

    return allok

def validateSubModule(reponame, repoBranch, submodule, submSha):
    submBrName = getNamingConvention(reponame, repoBranch)

    brExists = subMbranchExists(submodule["path"], submBrName)

    if (not brExists):
        return False, "Expected branch %s doesn't exist for the submodule: %s"%(submBrName, submodule["name"])

    if submSha is not getHead(submBrName, submodule["path"]):
        return False, "%s's submodule \"%s\" is not pointing to the head of submodule's release branch %s"%(reponame, submodule["name"], submBrName)

    return True, ""

def currentBranch():
    return tryFatal1("git rev-parse --abbrev-ref HEAD")

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
    global commitMessages

    # Determine all merges that occurred to target since branch deviated from it
    revList=breakStripStr(tryFatal("git log --merges --pretty=%%H %s...%s"%(target,branch)))
    log ("Merge commits: %s"%revList)

    mergeSubModules(branch, target)
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

                setSubModuleCommitOnSource(branch, target, sha) #this is for not producing any conflicts during the automerge of the parent branches

                mergeResult, err=sh("git merge --no-ff -m %s"%(lCommitMsg))
                if  err != 0:
                    log ("Conflict merging %s"%commitDetails)
                    reportMergeFailure(AutoMergeErrors.MergeError,branch, target, mergeResult)
                    return False
                commitMessages.append(lCommitMsg)
                log ("Succesfully merged %s"%commitDetails)


    log("All merge commits (if any) are now in target branch %s. Validating that branches %s and %s are completely merged."%(target, branch, target))
    # Test that we are fully merged
    sha=tryFatal1("git show -s --pretty=%h HEAD")

    output, err = sh("git merge --no-ff -m \"Test Merge\" %s"%branch )
    if err == 0:
        shaNew=tryFatal1("git show -s --pretty=%h HEAD")
    else:
        shaNew="0"
        log (output)

    if sha != shaNew:
        message="Branch %s is not fully merged into %s after merging all pull request \
merges. Do you have commits without PR? Manual intevention is required."%(branch, target)
        log(message)
        reportMergeFailure(AutoMergeErrors.MergeError,branch, target, message)
        return False


    return True

def setSubModuleCommitOnSource(srcbranch, target, sha):
    submodules = getSubModules()
    curPath = tryFatal1("pwd")
    tryFatal("git checkout %s"%srcbranch)

    for submodule in submodules:
        srcBrSubModuleSha = getShaOfSubModule(sha, submodule["path"])
        targetBrSubModuleSha = getShaOfSubModule(target, submodule["path"])

        if (srcBrSubModuleSha != targetBrSubModuleSha):

            chdir(submodulePath)
            tryFatal("git pull")
            tryFatal("git checkout %s"%targetBrSubModuleSha)
            chdir(curPath)

    tryFatal("git commit -a -m \"submodules level commit\"")

    #go back to original branch
    tryFatal("git checkout %s"%target)
    tryFatal("git submodule update")

#this returns the submodule paths in the repo

def gitUrl():
    #return "git.soma.salesforce.com:insights"
    return "github.com:navyasirugudi"

def getSubModules():
    if (not os.path.isfile(".gitmodules")):
        return []

    gitmfile = open(".gitmodules", "r")
    modules = []

    urlregex = "(.*)url(.*)=(.*)git@%s/(.*)"%gitUrl()
    pathregex = "(.*)path(.*)=(.*)"
    print urlregex
    print pathregex

    url = re.compile(urlregex)
    path = re.compile(pathregex)

    module = {}
    for line in gitmfile:
        print line
        if len(line) == 0:
            continue

        pmatch = path.match(line)
        umatch = url.match(line)

        if (pmatch is not None):
            print pmatch.groups()

        if (umatch is not None):
            print umatch.groups()

        if (umatch is not None and len(umatch.groups()) == 4):
            module["name"] = umatch.groups()[3].strip()

        elif (pmatch is not None and len(pmatch.groups()) == 3):
            module["path"] = pmatch.groups()[2].strip()

        if ("path" in module and "name" in module):
            print "Obtained subModule: %s"%module
            modules.append(module)
            module = {}

    return modules

#gets the sha of the head of the submodule under that branch
def getHead(branch, submodule):
    curPath = tryFatal1("pwd")

    chdir(submodule)
    tryFatal("git checkout %s"%branch)

    sha = tryFatal1("git show --format='%H'")

    chdir(curPath)
    tryFatal("git submodule update")

    return sha

def getShaOfSubModule(branch, submodule):
    curPath = tryFatal1("pwd")
    curbranch = currentBranch()

    tryFatal("git checkout %s"%branch)
    tryFatal("git submodule update")

    chdir(submodule)

    sha = tryFatal1("git show --format='%H'")

    chdir(curPath)

    tryFatal("git checkout %s"%curbranch)
    tryFatal("git submodule update")

    return sha

def getNamingConvention(reponame, branch):
    if branch == "master":
        return "master"

    return reponame + "_" + branch

def getRepoLink():
    #return "https://git.soma.salesforce.com/insights/(.*).git"
    return "https://github.com/navyasirugudi/(.*).git"

def getRepoName():
    url = tryFatal1("git config remote.origin.url")
    print "obtained url for repo name: %s"%url
    urlRegex = getRepoLink()
    urlMatcher = re.compile(urlRegex)

    matches = urlMatcher.match(url)
    #if (matches is None):
     #   return ""

    return matches.groups()[0]

def mergeSubModules(srcbranch, target):
    submodules = getSubModules()
    reponame = getRepoName()

    for submodule in submodules:
        #check submodule pointer to head of the corresponding release branch of the submodules on both src and target branches.

        targetBrSubModuleSha = getShaOfSubModule(target, submodule["path"])
        srcBrSubModuleSha = getShaOfSubModule(srcbranch, submodule["path"])

        if (srcBrSubModuleSha == targetBrSubModuleSha): #merge not required
            continue

        chdir(submodule["path"])

        if not autoMerge(getNamingConvention(reponame, srcbranch), getNamingConvention(reponame, target)): #Will parent be a submodule of the submodule again? Then this would become a circular loop. So far we have only one level on submodules
            return False, "Failed merging submodule: %s on %s"%(submodule["name"], reponame)

    return True, ""

def branchExists(branchName):
    tryFatal("pwd")
    print "verifying branch %s"%branchName
    sha, err = sh("git rev-parse --quiet --verify remotes/origin/%s"%branchName)
    print err
    return err == 0

def subMbranchExists(submodulePath, branchName):
    currPwd = tryFatal1("pwd")
    chdir(submodulePath)
    exists = branchExists(branchName)
    chdir(currPwd)

    return exists

# Push data to origin. In case of failure, attempt to pull latest version and retry up to 5 times
def pushChanges(old) :
    if not beforePushTestHook is None:
        beforePushTestHook()

    pushResult=""
    cb = currentBranch()

    for i in range(5):
        if not beforePushValidateHook is None:
            log("Start validation before push in %s"%cb)
            if not beforePushValidateHook():
                errMsg = "Validation before push in %s failed"%cb
                log (errMsg)
                reportMergeFailure(AutoMergeErrors.PushValidationError,cb, errMsg)
                return False

        #pushResult,err =sh("git push")
        err = 0
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
