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
run
