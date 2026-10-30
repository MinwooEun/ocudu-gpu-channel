const {chromium}=require('/tmp/ocg-html-qa-20261028/node_modules/playwright');
const fs=require('fs'),path=require('path');
(async()=>{const base='/home/minwoo/ocudu-work/profiling-20261029-causal';const out=__dirname;const browser=await chromium.launch({headless:true,executablePath:'/tmp/ocg-html-qa-20261028/browsers/chromium_headless_shell-1194/chrome-linux/headless_shell',args:['--disable-gpu','--disable-software-rasterizer','--use-gl=disabled']});const results=[];
for(const lang of ['ko','en']){
 const page=await browser.newPage();const errors=[],external=[];page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url())});await page.goto('file://'+path.join(base,`scaling-and-ue-phy.${lang}.html`));
 for(const width of [360,768,1440]){await page.setViewportSize({width,height:1000});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error(lang+' overflow '+width)}
 if(await page.locator('.core-tile').count()!==20)throw Error('core count');
 await page.click('[data-core-count="8"]');await page.click('[data-core="17"]');let detail=await page.locator('#core-detail').innerText();if(!detail.includes('UE0')||!detail.includes('UE3')||detail.includes('UE8'))throw Error('8 UE mask');
 await page.click('[data-core-count="16"]');detail=await page.locator('#core-detail').innerText();if(!detail.includes('UE8')||!detail.includes('UE11'))throw Error('16 UE mask');
 await page.click('[data-core="15"]');if(!(await page.locator('#core-detail').innerText()).includes('51'))throw Error('broker workers');
 await page.click('[data-core="5"]');await page.click('[data-core="0"]');await page.click('[data-core="17"]');
 for(const btn of await page.locator('[data-axis]').all()){await btn.click();let axis=await btn.getAttribute('data-axis');if(!await page.locator('#axis-'+axis).isVisible())throw Error('axis '+axis)}
 for(const btn of await page.locator('[data-flow]').all()){await btn.click();if(await btn.getAttribute('aria-pressed')!=='true')throw Error('flow state')}
 for(const btn of await page.locator('[data-location]').all()){await btn.click();if(await btn.getAttribute('aria-pressed')!=='true')throw Error('location state')}
 const ids=await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));if(new Set(ids).size!==ids.length)throw Error('duplicate ids');
 const links=await page.locator('a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));const missing=[];
 for(const href of links){if(!href)continue;if(href.startsWith('#')){if(!await page.locator(href).count())missing.push(href)}else if(!/^(https?:|mailto:)/.test(href)){if(!fs.existsSync(path.resolve(base,decodeURIComponent(href.split('#')[0]))))missing.push(href)}}
 if(missing.length)throw Error(lang+' missing links '+JSON.stringify(missing));
 if(lang==='en'&&/[가-힣]/.test(await page.locator('main').innerText()))throw Error('visible Korean in English document');
 await page.setViewportSize({width:1440,height:1100});await page.locator('[data-axis="ue"]').click();await page.locator('[data-flow="newrx"]').click();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(out,lang+'-overview.png'),fullPage:false});await page.locator('#core-sharing').screenshot({path:path.join(out,lang+'-core-sharing.png')});await page.locator('#uegpu').screenshot({path:path.join(out,lang+'-gpu-ue.png')});
 await page.setViewportSize({width:390,height:844});await page.locator('#core-sharing').screenshot({path:path.join(out,lang+'-core-mobile.png')});
 await page.emulateMedia({media:'print'});for(const panel of await page.locator('#axes .panel').all())if(!await panel.isVisible())throw Error('print axes');
 if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));results.push({language:lang,widths:[360,768,1440],cores:20,coreToggle:'8/16 mapping checked',links:links.length,errors,externalRequests:external,print:'all scaling panels visible'});await page.close();
}
await browser.close();fs.writeFileSync(path.join(out,'qa.json'),JSON.stringify(results,null,2));console.log('PASS',JSON.stringify(results));})().catch(e=>{console.error(e);process.exit(1)})
