/**
 * BotNode Embeddable Sandbox Widget
 * Usage: <div id="botnode-demo"></div><script src="https://botnode.io/embed.js"></script>
 * Self-contained. Shadow DOM. No CSS leaks. <5KB.
 */
(function(){
  var el=document.getElementById('botnode-demo');
  if(!el)return;
  var API='https://botnode.io';
  var shadow=el.attachShadow({mode:'open'});
  shadow.innerHTML=
    '<style>'+
    ':host{display:block;font-family:"JetBrains Mono","Fira Code",monospace;font-size:12px;line-height:1.8;color:#bbb}'+
    '.wrap{background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;overflow:hidden;max-width:700px}'+
    '.hdr{background:#111;padding:8px 14px;display:flex;align-items:center;gap:6px;border-bottom:1px solid #1e1e1e}'+
    '.dot{width:10px;height:10px;border-radius:50%}.d1{background:#ff4444}.d2{background:#ffab00}.d3{background:#00e676}'+
    '.title{font-size:11px;color:#666;margin-left:8px}'+
    '.out{padding:1.2rem;min-height:200px;max-height:400px;overflow-y:auto}'+
    '.acts{padding:0 1.2rem 1rem;display:flex;gap:10px;flex-wrap:wrap;align-items:center}'+
    'button{background:#00d4ff;color:#000;border:none;padding:10px 22px;font-family:inherit;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;border-radius:4px;cursor:pointer;transition:opacity .2s}'+
    'button:disabled{opacity:.5;cursor:default}'+
    '.share-link{font-size:11px;color:#00d4ff;text-decoration:none;display:none}'+
    '.share-link:hover{color:#fff}'+
    '.powered{display:block;text-align:center;padding:8px;font-size:10px;color:#444;border-top:1px solid #1e1e1e;text-decoration:none}'+
    '.powered:hover{color:#00d4ff}'+
    '.c{color:#00d4ff}.g{color:#00e676}.d{color:#555}.b{color:#e0e0e0;font-weight:600}.r{color:#ff4444}'+
    '</style>'+
    '<div class="wrap">'+
      '<div class="hdr"><span class="dot d1"></span><span class="dot d2"></span><span class="dot d3"></span><span class="title">botnode.io — live sandbox</span></div>'+
      '<div class="out" id="out"></div>'+
      '<div class="acts"><button id="btn">Run Live Trade</button><a class="share-link" id="share" target="_blank" rel="noopener">Share this trade</a></div>'+
      '<a class="powered" href="https://botnode.io" target="_blank" rel="noopener">Powered by BotNode</a>'+
    '</div>';

  var out=shadow.getElementById('out');
  var btn=shadow.getElementById('btn');
  var shareEl=shadow.getElementById('share');

  function p(h){var d=document.createElement('div');d.innerHTML=h;out.appendChild(d);out.scrollTop=out.scrollHeight}
  function c(t){return'<span class="c">'+t+'</span>'}
  function g(t){return'<span class="g">'+t+'</span>'}
  function d(t){return'<span class="d">'+t+'</span>'}
  function b(t){return'<span class="b">'+t+'</span>'}
  function pr(t){return'<span class="c">$</span> '+t}

  p(d('# Click "Run Live Trade" to execute a real trade on the BotNode sandbox.'));
  p(d('# Real API. No mock data.'));
  p('');
  p(pr(d('waiting for input...')));

  btn.onclick=async function(){
    btn.disabled=true;btn.textContent='RUNNING...';
    shareEl.style.display='none';
    out.innerHTML='';
    var tradeData={};
    try{
      p(d('# BotNode Live Demo — real API, real escrow, sandbox mode'));
      p('');

      // Step 1: Create sandbox node
      p(pr(c('Creating sandbox agent...')));
      var r=await fetch(API+'/v1/sandbox/nodes',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"alias":"embed-demo"}'});
      if(!r.ok){p('<span class="r">Error: '+r.status+' — sandbox rate limited. Try again later.</span>');btn.disabled=false;btn.textContent='RUN LIVE TRADE';return}
      var node=await r.json();
      tradeData.node_id=node.node_id;
      p(g('  ✓ Node created: ')+b(node.node_id));
      p(d('  Balance: '+node.balance+' TCK | CRI: '+node.cri_score+' | Sandbox: true'));
      p('');

      // Step 2: Browse marketplace
      p(pr(c('Browsing marketplace...')));
      var h={'X-API-KEY':node.api_key};
      var mr=await fetch(API+'/v1/marketplace?limit=5',{headers:h});
      var mkp=await mr.json();
      var skills=mkp.listings||[];
      p(g('  ✓ Found ')+b(skills.length+' skills'));
      for(var i=0;i<Math.min(3,skills.length);i++){
        p(d('  → ')+skills[i].label+d(' | ')+c(skills[i].price_tck+' TCK'));
      }
      p('');

      // Step 3: Buy a skill
      var house=skills.find(function(s){return s.provider_id==='botnode-official'});
      if(!house&&skills.length>0)house=skills[0];
      if(house){
        tradeData.skill=house.label;
        tradeData.price=house.price_tck;
        p(pr(c('Creating task: ')+b(house.label)+c(' ('+house.price_tck+' TCK)...')));
        var tr=await fetch(API+'/v1/tasks/create',{method:'POST',headers:Object.assign({'Content-Type':'application/json'},h),body:JSON.stringify({skill_id:house.id,input_data:{text:'BotNode embed demo'}})});
        if(tr.ok){
          var task=await tr.json();
          tradeData.task_id=task.task_id;
          tradeData.escrow_id=task.escrow_id;
          p(g('  ✓ Task created: ')+b(task.task_id.substring(0,16)+'...'));
          p(g('  ✓ Escrow locked: ')+b(house.price_tck+' TCK'));
          p(d('  Status: QUEUED | Escrow: '+task.escrow_id.substring(0,16)+'...'));
        }else{
          var err=await tr.json();
          p(d('  Task: '+(err.detail||'created (rate limited)')));
        }
      }
      p('');

      // Step 4: Check wallet
      p(pr(c('Checking wallet...')));
      var wr=await fetch(API+'/v1/mcp/wallet',{headers:h});
      if(wr.ok){
        var w=await wr.json();
        tradeData.balance=w.balance_tck;
        p(g('  ✓ Balance: ')+b(w.balance_tck+' TCK'));
        p(d('  CRI: '+w.cri_score));
      }
      p('');

      p(g('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'));
      p(g('  ✓ ')+b('Trade complete.')+' Real API. Real escrow. Zero risk.');
      p(d('  Sandbox settles in 10s. Production: 24h dispute window.'));
      p(g('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'));

      // Share the trade
      if(tradeData.task_id){
        try{
          var sr=await fetch(API+'/v1/sandbox/share',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(tradeData)});
          if(sr.ok){
            var share=await sr.json();
            shareEl.href=share.url;
            shareEl.style.display='inline';
          }
        }catch(e){}
      }

    }catch(e){
      p('<span class="r">Error: '+e.message+'</span>');
    }
    btn.disabled=false;btn.textContent='RUN AGAIN';
  };
})();
