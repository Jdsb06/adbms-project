set pagination off
set confirm off
set debuginfod enabled off
set startup-with-shell off
break where.c:5903 if pWInfo->nLevel > 1
commands
silent
printf "PROJECT_SOLVER nLoop=%d mxChoice=%d nRowEst=%d nOrderBy=%d star=%d\n", nLoop, mxChoice, nRowEst, nOrderBy, pWInfo->bStarUsed
bt 5
print pWInfo->pLoops->maskSelf
print pWInfo->pLoops->prereq
print pWInfo->pLoops->rSetup
print pWInfo->pLoops->rRun
print pWInfo->pLoops->nOut
continue
end
break where.c:6116 if pWInfo->nLevel == 3 && iLoop == 1 && pWLoop->cId == '4'
commands
silent
printf "PROJECT_REPLACEMENT depth=%d candidate=%c%c old=%c%c newCost=%d oldCost=%d\n", iLoop+1, pFrom->aLoop[0]->cId, pWLoop->cId, pTo->aLoop[0]->cId, pTo->aLoop[1]->cId, rCost, pTo->rCost
print pFrom->maskLoop
print pWLoop->prereq
print pWLoop->rRun
print pFrom->nRow
continue
end
run
