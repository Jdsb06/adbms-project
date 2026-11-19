// Optional UI checks: requires Playwright and a local Chrome/Chromium executable.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
(async()=>{
  const root=path.resolve(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,'evidence/project.json'),'utf8'));
  const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-gpu']});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],requests=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
    await page.goto(pathToFileURL(path.join(root,'viewer/index.html')).href);
    assert.equal(await page.locator('#error').isVisible(),false);
    assert.match(await page.locator('#expansion-summary').innerText(),/6 distinct table orders shown · 10 logged decisions/);
    const branch = code => page.locator(`#branch-graph button[data-path="${code}"]`);
    await page.click('#lesson-start');
    assert.match(await page.locator('#lesson-title').innerText(),/Start with region/);
    assert.equal(await branch('0').getAttribute('aria-pressed'),'true');
    for (const code of ['02','04','20','03','046']) {
      await page.click('#lesson-next');
      assert.equal(await branch(code).getAttribute('aria-pressed'),'true');
    }
    await page.click('#lesson-back');
    assert.equal(await branch('03').getAttribute('aria-pressed'),'true');
    await page.click('#lesson-next');
    await page.click('#lesson-next');
    assert.equal(await page.locator('#lesson-start').isVisible(),true);
    await page.click('#prev');
    await page.click('#replay-toggle');
    assert.match(await page.locator('#replay-counter').innerText(),/Decision 1 of 10 · New 02/);
    await page.click('#replay-next');
    assert.match(await page.locator('#replay-counter').innerText(),/Decision 2 of 10 · Update 04/);
    assert.equal(await branch('04').getAttribute('aria-pressed'),'true');
    assert.match(await page.locator('#branch-inspector .cost-comparison').innerText(),/Cost 56.*Cost 67/s);
    await page.click('#replay-play');
    await page.waitForFunction(()=>document.getElementById('replay-counter').textContent.includes('New 05'));
    await page.click('#replay-play');
    await page.locator('#replay-position').fill('10');
    assert.equal(await page.locator('#replay-next').isDisabled(),true);
    await page.selectOption('#prefix-filter','0');
    assert.match(await page.locator('#replay-counter').innerText(),/Decision 1 of 3 · New 02/);
    await page.selectOption('#prefix-filter','all');
    await page.click('#replay-toggle');
    assert.equal(await page.locator('#branch-graph .branch-order').count(),6);
    assert.match(await branch('02').innerText(),/New.*Replaced by 04/s);
    assert.match(await branch('04').innerText(),/Update.*Retained/s);
    assert.equal(await branch('20').getAttribute('data-kind'),'Skip');
    await branch('03').click();
    assert.match(await page.locator('#branch-inspector').innerText(),/needs c earlier.*Inferred from wherePathSolver/s);
    assert.match(await page.locator('#access-example').innerText(),/0 = Scan region \(r\).*2 = Scan nation \(n\)/);
    await page.check('#include-used');
    assert.equal(await branch('00').getAttribute('data-kind'),'Ineligible');
    await page.uncheck('#include-used');
    await page.click('#prev');
    assert.match(await page.locator('#expansion-summary').innerText(),/3 distinct table orders shown/);
    assert.match(await page.locator('#branch-graph .branch-root').innerText(),/Empty starting path/);
    await page.click('#next');
    await page.click('#next');
    assert.equal(await page.locator('#branch-graph .branch-root code').allTextContents().then(items=>items.join(',')),'04,26,05');
    assert.match(await branch('046').innerText(),/Update.*Retained/s);
    // Every graph event and survivor should reconcile with the recorded round.
    const mismatches = await page.evaluate(() => {
      const evidence = JSON.parse(document.getElementById('project-data').textContent);
      const failures = [];
      for (const run of evidence.runs) {
        for (const pass of run.trace.blocks[0].passes) {
          for (const round of pass.rounds) {
            const variants = expansionBranches(pass, round, startingPaths(pass, round), false)
              .flatMap(branch => branch.orders.flatMap(order => order.variants));
            const lines = variants.filter(item => item.source_line).map(item => item.source_line).sort();
            const expectedLines = round.events.map(event => event.source_line).sort();
            const survivors = variants.filter(item => item.survived).map(item => item.path).sort();
            const expectedSurvivors = round.retained.map(item => item.path).sort();
            if (String(lines) !== String(expectedLines) || String(survivors) !== String(expectedSurvivors)) {
              failures.push([run.id, pass.id, round.depth]);
            }
          }
        }
      }
      return failures;
    });
    assert.deepEqual(mismatches,[]);
    await page.selectOption('#search-view','retained');
    for(let i=0;i<data.runs.length;i++){
      const run=data.runs[i],block=run.trace.blocks[0];
      await page.selectOption('#run',String(i));
      assert.equal(await page.locator('#stat-limit').innerText(),String(block.path_limit));
      assert.equal(await page.locator('#join-graph rect').count(),block.table_count);
      assert.deepEqual((await page.locator('#join-graph text').allTextContents()).sort(),run.graph.nodes.map(n=>n.id).sort());
      for(let p=0;p<block.passes.length;p++){
        await page.selectOption('#pass',String(p));
        for(let r=0;r<block.passes[p].rounds.length;r++){
          const round=block.passes[p].rounds[r];
          assert.equal(await page.locator('#stat-retained').innerText(),String(round.retained.length));
          assert.equal(await page.locator('#stat-events').innerText(),String(round.events.length));
          assert.equal(await page.locator('#events tr').count(),round.events.length);
          if(r<block.passes[p].rounds.length-1)await page.click('#next');
        }
        assert.equal(await page.locator('#next').isDisabled(),true);
        await page.locator('#search-graph g[role=button]').last().focus();
        await page.keyboard.press('Enter');
        assert.equal(await page.locator('#detail-kind').innerText(),'Retained');
      }
    }
    await page.selectOption('#run','1');
    await page.selectOption('#event-filter','Update');
    assert.equal(await page.locator('#events tr').count(),2);
    await page.locator('#events tr').first().click();
    assert.match(await page.locator('#detail').innerText(),/Replaces 02/);
    await page.selectOption('#event-filter','all');
    const figureDir=process.env.VIEWER_FIGURE_DIR||path.join(root,'output/figures');
    fs.mkdirSync(figureDir,{recursive:true});
    await page.screenshot({path:path.join(figureDir,'viewer_three_table.png'),fullPage:true});
    await page.locator('.detail-panel').screenshot({path:path.join(figureDir,'three_table_inspector.png')});
    await page.selectOption('#run','3');
    await page.selectOption('#pass','1');
    for(let i=0;i<7;i++)await page.click('#next');
    await page.screenshot({path:path.join(figureDir,'viewer_q8.png'),fullPage:true});
    const figurePage=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:3});
    await figurePage.goto(pathToFileURL(path.join(root,'viewer/index.html')).href);
    await figurePage.locator('#expansion-view').screenshot({path:path.join(figureDir,'three_table_expansion.png')});
    await figurePage.selectOption('#search-view','retained');
    const graphBox=await figurePage.locator('#search-graph').boundingBox();
    await figurePage.screenshot({path:path.join(figureDir,'three_table_paths.png'),clip:{x:graphBox.x,y:graphBox.y,width:385,height:200}});
    await figurePage.selectOption('#run','3');
    assert.equal(await figurePage.locator('#join-graph rect').count(),8);
    await figurePage.locator('#join-graph').screenshot({path:path.join(figureDir,'q8_join_graph.png')});
    await figurePage.close();
    await page.setViewportSize({width:390,height:844});
    await page.selectOption('#search-view','expansion');
    await page.selectOption('#prefix-filter','all');
    assert.equal(await page.locator('#branch-graph .branch-card[data-kind="Unlogged"]').count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(figureDir,'viewer_mobile.png'),fullPage:true});
    await page.locator('#file').setInputFiles({name:'unsupported.json',mimeType:'application/json',buffer:Buffer.from('{"schema_version":99}')});
    await page.locator('#error').waitFor({state:'visible'});
    assert.match(await page.locator('#error').innerText(),/Unsupported evidence format/);
    const corrupt=JSON.parse(JSON.stringify(data));corrupt.runs[0].trace.blocks[0].solution.path='00';
    await page.locator('#file').setInputFiles({name:'corrupt.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(corrupt))});
    await page.waitForFunction(()=>document.getElementById('error').textContent.includes('Final solution disagrees'));
    await page.locator('#file').setInputFiles(path.join(root,'evidence/project.json'));
    await page.locator('#error').waitFor({state:'hidden'});
    await page.goto(pathToFileURL(path.join(root,'viewer/template.html')).href);
    assert.equal(await page.locator('#template-notice a').isVisible(),true);
    await page.locator('#template-notice a').click();
    assert.equal(await page.locator('#lesson-start').isVisible(),true);
    assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
    console.log('Viewer passed all runs, passes, rounds, selection, filtering, offline, mobile and file-import checks.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
