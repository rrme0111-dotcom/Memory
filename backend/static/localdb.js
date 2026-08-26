/* ============================================================
 * 记忆漩涡 MemoryVortex · 本地数据层（localdb.js）
 * ============================================================
 * 把 Python 后端的数据库 + 业务逻辑整体搬到浏览器 IndexedDB，
 * 让应用在无服务器环境下完整运行（PWA 离线模式）。
 *
 * 架构：
 *   window.fetch 被全局拦截 → /api/* 路由到本模块 → 读写 IndexedDB
 *   /uploads/* 的图片引用被替换为 blob: URL，直接在 <img>/CSS 中渲染
 *
 * 对象存储（对齐 db.py 表结构）：
 *   memories / perspectives / comments / anniversaries
 *   growth_subjects / growth_milestones / timeline_nodes / invite_members
 *   users / sessions / files(Blob)
 * ============================================================ */
(function(){
'use strict';

/* ---------- 常量 ---------- */
var DB_NAME='memory_vortex';
var DB_VER=1;
var SEED_OWNER='seed';
var LOCAL_OWNER='local';
var SCENE_NAMES={personal:'个人',couple:'情侣',friend:'友情',growth:'成长'};
var GROWTH_KIND_NAMES={baby:'宝宝',pet:'宠物',other:'成长主体'};
var GROWTH_KIND_ICONS={baby:'baby',pet:'pet',other:'baby'};
var ALLOWED_EXT={jpg:1,jpeg:1,png:1,gif:1,webp:1,mp4:1,mov:1,webm:1,m4a:1,mp3:1};
var DB=null;            // IndexedDB 实例
var TEMPLATE=null;      // test_data.json 模板（启动时加载）
var blobCache={};       // fileKey → objectURL（运行时 blob URL 缓存）
var nextId={};          // 各 store 的自增 ID 计数器

/* ---------- 工具：日期格式化（对齐 main.py） ---------- */
function now(){return new Date();}
function pad2(n){return n<10?'0'+n:''+n;}
function fmtHM(d){return d?pad2(d.getHours())+':'+pad2(d.getMinutes()):'';}
function fmtDate(d){
  if(!d)return '';
  return d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日';
}
function fmtDateShort(d){
  if(!d)return '';
  return d.getFullYear()+'.'+pad2(d.getMonth()+1)+'.'+pad2(d.getDate());
}
function parseDate(s){
  if(!s)return null;
  var m=/(\d{4})-(\d{1,2})-(\d{1,2})/.exec(s);
  if(m)return new Date(+m[1],+m[2]-1,+m[3]);
  m=/(\d{4})年(\d{1,2})月(\d{1,2})日/.exec(s);
  if(m)return new Date(+m[1],+m[2]-1,+m[3]);
  return null;
}
function parseDateTime(s){
  if(!s)return null;
  var d=parseDate(s);
  if(!d)return null;
  var m=/(\d{1,2}):(\d{2})/.exec(s);
  if(m){d.setHours(+m[1]);d.setMinutes(+m[2]);}
  return d;
}
function daysBetween(a,b){return Math.round((b-a)/86400000);}

/* ---------- 工具：随机 hex（对齐 uploads.py） ---------- */
function randomHex(n){
  var s='';
  var chars='0123456789abcdef';
  for(var i=0;i<n;i++)s+=chars[Math.floor(Math.random()*16)];
  return s;
}
function genFileKey(ext){
  return randomHex(24)+'.'+ext;
}

/* ---------- IndexedDB 打开 + 建表 ---------- */
function openDB(){
  return new Promise(function(resolve,reject){
    var req=indexedDB.open(DB_NAME,DB_VER);
    req.onupgradeneeded=function(e){
      var db=e.target.result;
      if(!db.objectStoreNames.contains('memories')){
        var s=db.createObjectStore('memories',{keyPath:'id',autoIncrement:true});
        s.createIndex('scene','scene',{unique:false});
        s.createIndex('owner_id','owner_id',{unique:false});
      }
      if(!db.objectStoreNames.contains('perspectives')){
        var p=db.createObjectStore('perspectives',{keyPath:'id',autoIncrement:true});
        p.createIndex('memory_id','memory_id',{unique:false});
      }
      if(!db.objectStoreNames.contains('comments')){
        var c=db.createObjectStore('comments',{keyPath:'id',autoIncrement:true});
        c.createIndex('memory_id','memory_id',{unique:false});
      }
      if(!db.objectStoreNames.contains('anniversaries'))
        db.createObjectStore('anniversaries',{keyPath:'id',autoIncrement:true});
      if(!db.objectStoreNames.contains('growth_subjects'))
        db.createObjectStore('growth_subjects',{keyPath:'id',autoIncrement:true});
      if(!db.objectStoreNames.contains('growth_milestones')){
        var gm=db.createObjectStore('growth_milestones',{keyPath:'id',autoIncrement:true});
        gm.createIndex('subject_id','subject_id',{unique:false});
      }
      if(!db.objectStoreNames.contains('timeline_nodes'))
        db.createObjectStore('timeline_nodes',{keyPath:'id',autoIncrement:true});
      if(!db.objectStoreNames.contains('invite_members'))
        db.createObjectStore('invite_members',{keyPath:'id',autoIncrement:true});
      if(!db.objectStoreNames.contains('users')){
        var u=db.createObjectStore('users',{keyPath:'id',autoIncrement:true});
        u.createIndex('username','username',{unique:false});
      }
      if(!db.objectStoreNames.contains('sessions'))
        db.createObjectStore('sessions',{keyPath:'token'});
      if(!db.objectStoreNames.contains('files'))
        db.createObjectStore('files',{keyPath:'key'});
      if(!db.objectStoreNames.contains('meta'))
        db.createObjectStore('meta',{keyPath:'key'});
    };
    req.onsuccess=function(e){DB=e.target.result;resolve(DB);};
    req.onerror=function(e){reject(e.target.error);};
  });
}

/* ---------- IndexedDB 通用读写 ---------- */
function txGet(store,key){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readonly');
    var r=t.objectStore(store).get(key);
    r.onsuccess=function(){resolve(r.result);};
    r.onerror=function(){reject(r.error);};
  });
}
function txGetAll(store){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readonly');
    var r=t.objectStore(store).getAll();
    r.onsuccess=function(){resolve(r.result||[]);};
    r.onerror=function(){reject(r.error);};
  });
}
function txGetAllByIndex(store,indexName,value){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readonly');
    var r=t.objectStore(store).index(indexName).getAll(value);
    r.onsuccess=function(){resolve(r.result||[]);};
    r.onerror=function(){reject(r.error);};
  });
}
function txPut(store,obj){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readwrite');
    var r=t.objectStore(store).put(obj);
    r.onsuccess=function(){resolve(r.result);};
    r.onerror=function(){reject(r.error);};
  });
}
function txDelete(store,key){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readwrite');
    var r=t.objectStore(store).delete(key);
    r.onsuccess=function(){resolve(true);};
    r.onerror=function(){reject(r.error);};
  });
}
function txCount(store){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readonly');
    var r=t.objectStore(store).count();
    r.onsuccess=function(){resolve(r.result||0);};
    r.onerror=function(){reject(r.error);};
  });
}
function txClear(store){
  return new Promise(function(resolve,reject){
    var t=DB.transaction(store,'readwrite');
    var r=t.objectStore(store).clear();
    r.onsuccess=function(){resolve(true);};
    r.onerror=function(){reject(r.error);};
  });
}

/* ---------- 自增 ID ---------- */
function getNextId(store){
  return txGetAll(store).then(function(all){
    var max=0;
    for(var i=0;i<all.length;i++)if(all[i].id>max)max=all[i].id;
    return max+1;
  });
}

/* ---------- 模板加载 ---------- */
function loadTemplate(){
  return fetch('test_data.json').then(function(r){return r.json();});
}

/* ---------- 种子数据清除（对齐 db.py _migrate 的 seed 清理） ----------
 * v0.9.3：不再把模板假数据导入 IndexedDB；同时把历史版本已导入的
 * owner_id === 'seed' 行全部删除（含级联的多视角/留言），保证新用户
 * 看到真实的空状态，而不是测试演示数据。
 */
function purgeSeeds(){
  return Promise.all([
    txGetAll('memories'),txGetAll('anniversaries'),
    txGetAll('growth_subjects'),txGetAll('growth_milestones'),
    txGetAll('timeline_nodes'),txGetAll('invite_members')
  ]).then(function(res){
    var seedIds={};
    res[0].forEach(function(m){if(m.owner_id===SEED_OWNER)seedIds[m.id]=1;});
    return Promise.all([txGetAll('perspectives'),txGetAll('comments')]).then(function(eng){
      var tasks=[];
      eng[0].forEach(function(p){if(seedIds[p.memory_id])tasks.push(txDelete('perspectives',p.id));});
      eng[1].forEach(function(c){if(seedIds[c.memory_id])tasks.push(txDelete('comments',c.id));});
      res[0].forEach(function(m){if(m.owner_id===SEED_OWNER)tasks.push(txDelete('memories',m.id));});
      res[1].forEach(function(a){if(a.owner_id===SEED_OWNER)tasks.push(txDelete('anniversaries',a.id));});
      res[2].forEach(function(s){if(s.owner_id===SEED_OWNER)tasks.push(txDelete('growth_subjects',s.id));});
      res[3].forEach(function(ms){if(ms.owner_id===SEED_OWNER)tasks.push(txDelete('growth_milestones',ms.id));});
      res[4].forEach(function(n){if(n.owner_id===SEED_OWNER)tasks.push(txDelete('timeline_nodes',n.id));});
      res[5].forEach(function(im){if(im.owner_id===SEED_OWNER)tasks.push(txDelete('invite_members',im.id));});
      return Promise.all(tasks);
    });
  });
}

/* ---------- 文件 / Blob URL 管理 ---------- */
function loadAllBlobs(){
  return txGetAll('files').then(function(files){
    files.forEach(function(f){
      if(f.blob&&!blobCache[f.key]){
        blobCache[f.key]=URL.createObjectURL(f.blob);
      }
    });
  });
}
function resolveFileUrl(key){
  if(blobCache[key])return blobCache[key];
  return '/uploads/'+key;  // 回退（未加载时）
}
function storeBlob(key,blob){
  return txPut('files',{key:key,blob:blob}).then(function(){
    if(!blobCache[key])blobCache[key]=URL.createObjectURL(blob);
    return blobCache[key];
  });
}

/* ---------- 业务逻辑（对齐 main.py build_*） ---------- */
function firstCover(m){
  var media=m.media||[];
  return media.length?media[0]:null;
}
function firstImageCover(m){
  var media=m.media||[],i;
  for(i=0;i<media.length;i++){
    var k=(media[i].kind||'').toLowerCase();
    if(/^(png|jpe?g|gif|webp)$/.test(k))return media[i];
  }
  return null;
}
function memoryMeta(m,pcount,ccount){
  if(m.meta_override)return m.meta_override;
  var parts=[];
  if(m.timestamp_type==='fuzzy'){parts.push('模糊时间');if(m.fuzzy_label)parts.push(m.fuzzy_label);}
  else{parts.push(m.source==='user'?'自定义时间戳':'');}
  if(m.emotions&&m.emotions.length)parts.push(m.emotions.join(' · '));
  var eng=[];
  if(pcount>1)eng.push(pcount+'条多视角');
  if(ccount>0)eng.push(ccount+'条留言');
  if(eng.length)parts.push(eng.join(' · '));
  return parts.filter(function(p){return p;}).join(' · ');
}
function fmtMemoryDate(m,now){
  if(!m.precise_at)return m.fuzzy_label||'记不清的时间';
  var d=new Date(m.precise_at);
  if(d.getFullYear()===now.getFullYear())return (d.getMonth()+1)+'月'+d.getDate()+'日 '+fmtHM(d);
  return fmtDate(d)+' '+fmtHM(d);
}
function timelineItem(m,now,pcount,ccount){
  return {
    mid:m.id,scene:m.scene,
    time:m.precise_at?fmtHM(new Date(m.precise_at)):(m.fuzzy_note||m.fuzzy_label||''),
    feel:m.feel,meta:memoryMeta(m,pcount,ccount),
    dateLabel:fmtMemoryDate(m,now),cover:fixCover(firstCover(m))
  };
}
function buildTimeline(memories,now,pcounts,ccounts){
  pcounts=pcounts||{};ccounts=ccounts||{};
  var groups=[],fuzzy={};
  memories.forEach(function(m){
    if(m.timestamp_type==='fuzzy'||!m.precise_at){
      var label=m.fuzzy_label||'记不清的时间';
      if(!fuzzy[label])fuzzy[label]=[];
      fuzzy[label].push(timelineItem(m,now,pcounts[m.id]||0,ccounts[m.id]||0));
    } else {
      var d=new Date(m.precise_at);
      var title=fmtDate(d);
      if(d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate())title+=' · 今天';
      var item=timelineItem(m,now,pcounts[m.id]||0,ccounts[m.id]||0);
      if(groups.length&&groups[groups.length-1].date===title)groups[groups.length-1].items.push(item);
      else groups.push({date:title,items:[item]});
    }
  });
  Object.keys(fuzzy).sort().reverse().forEach(function(label){
    groups.push({date:label,items:fuzzy[label]});
  });
  return groups;
}
function buildSceneView(memories,now,pcounts,ccounts){
  pcounts=pcounts||{};ccounts=ccounts||{};
  var cards=memories.map(function(m){
    var d=m.precise_at?new Date(m.precise_at):null;
    var timeStr='';
    if(d){
      timeStr=fmtHM(d);
      if(d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate())timeStr='今晚 '+timeStr;
      else timeStr=(d.getMonth()+1)+'月'+d.getDate()+'日 '+timeStr;
    } else {timeStr=m.fuzzy_label||'';}
    var dateLabel;
    if(!d)dateLabel=m.fuzzy_label||'记不清的时间';
    else if(d.getFullYear()===now.getFullYear())dateLabel=(d.getMonth()+1)+'月'+d.getDate()+'日 '+fmtHM(d);
    else dateLabel=fmtDate(d)+' '+fmtHM(d);
    return {
      mid:m.id,
      type:(m.media&&m.media.length)||m.voice?'media':'text',
      time:timeStr,dateLabel:dateLabel,scene:m.scene,feel:m.feel,
      voice:m.voice,emotions:m.emotions||[],cover:fixCover(firstCover(m)),
      meta:m.meta_override||(ccounts[m.id]?ccounts[m.id]+'条留言':(m.timestamp_type==='fuzzy'?m.fuzzy_label:null))
    };
  });
  return {groupTitle:now.getFullYear()+'年'+(now.getMonth()+1)+'月',cards:cards};
}
function buildOtd(templateOtd,memories,now){
  /* v0.9.3：不再把模板演示卡片（婚礼前夜/搬来上海等假数据）拼进响应，
   * 仅展示数据库中同月同日（往年）的真实记忆，新用户看到空状态。 */
  var cards=[];
  memories.forEach(function(m){
    if(!m.precise_at)return;
    var d=new Date(m.precise_at);
    if(d.getFullYear()>=now.getFullYear())return;
    if(d.getMonth()!==now.getMonth()||d.getDate()!==now.getDate())return;
    var yearsAgo=now.getFullYear()-d.getFullYear();
    cards.push({
      scene:m.scene,date:fmtDateShort(d),feel:m.feel,
      meta:yearsAgo+'年前 · '+((m.emotions&&m.emotions.length)?m.emotions.join(' · '):(SCENE_NAMES[m.scene]||m.scene))
    });
  });
  return {title:(now.getMonth()+1)+'月'+now.getDate()+'日 · 往年今日',cards:cards};
}

/* 纪念日 */
function annivDate(year,month,day){
  var d=new Date(year,month-1,day);
  return isNaN(d.getTime())?null:d;
}
function annivCoverMap(annivs){
  var cmap={};
  return annivs.reduce(function(p,a){
    if(!a.linked_memory_id)return p;
    return p.then(function(){
      return txGet('memories',a.linked_memory_id);
    }).then(function(m){
      cmap[a.linked_memory_id]=m?firstImageCover(m):null;
    });
  },Promise.resolve()).then(function(){return cmap;});
}
function fixCover(c){
  if(!c)return null;
  return {key:c.key,url:resolveFileUrl(c.key),kind:c.kind};
}
function buildAnniversaries(annivs,now,coverMap){
  coverMap=coverMap||{};
  var items=annivs.map(function(a){
    var today=now;today.setHours(0,0,0,0);
    var thisYear=annivDate(today.getFullYear(),a.month,a.day);
    var nxt=null;
    if(thisYear&&thisYear>=today)nxt=thisYear;
    else if(a.is_recurring)nxt=annivDate(today.getFullYear()+1,a.month,a.day);
    var daysLeft,note,dateLabel;
    if(nxt){
      daysLeft=daysBetween(today,nxt);
      var suffix=daysLeft===0?'就是今天':'还有 '+daysLeft+' 天';
      note=a.is_recurring?'每年重复 · '+suffix:suffix;
      dateLabel=nxt.getFullYear()+'年'+(nxt.getMonth()+1)+'月'+nxt.getDate()+'日';
    } else {
      daysLeft=null;
      var passed=thisYear?daysBetween(thisYear,today):0;
      note='已过 '+passed+' 天';
      dateLabel=thisYear?thisYear.getFullYear()+'年'+(thisYear.getMonth()+1)+'月'+thisYear.getDate()+'日':'';
    }
    if(a.lunar_label)dateLabel+=' · '+a.lunar_label;
    else if(a.is_lunar)dateLabel+=' · 农历';
    return {
      id:a.id,mid:a.linked_memory_id,day:String(a.day),month:a.month+'月',
      name:a.name,note:note,daysLeft:daysLeft,recurring:a.is_recurring,
      dateLabel:dateLabel,date:dateLabel,
      cover:a.linked_memory_id?(coverMap[a.linked_memory_id]?fixCover(coverMap[a.linked_memory_id]):null):null
    };
  });
  items.sort(function(a,b){
    var an=a.daysLeft===null?1:0,bn=b.daysLeft===null?1:0;
    if(an!==bn)return an-bn;
    return (a.daysLeft||1e6)-(b.daysLeft||1e6);
  });
  var nextItem=items.find(function(x){return x.daysLeft!==null;});
  if(!nextItem&&items.length)nextItem=items[0];
  var nextView=nextItem?{name:nextItem.name,daysLeft:nextItem.daysLeft||0,date:nextItem.dateLabel,cover:nextItem.cover}
    :{name:'还没有纪念日',daysLeft:0,date:'点击右上角 + 标记第一条'};
  return {next:nextView,count:items.length,list:items};
}

/* 成长追踪 */
function ageLabel(birthday,today){
  if(birthday>today)return '刚记录';
  var years=today.getFullYear()-birthday.getFullYear();
  var months=today.getMonth()-birthday.getMonth()-(today.getDate()<birthday.getDate()?1:0);
  if(months<0){years--;months+=12;}
  if(years>0)return months>0?years+'岁'+months+'个月':years+'岁';
  if(months>0)return months+'个月';
  var days=daysBetween(birthday,today);
  return days>0?days+'天':'今天出生';
}
function daysRelLabel(days){
  if(days<=0)return '今天';
  if(days===1)return '昨天';
  if(days<=365)return days+'天前';
  return '';
}
function buildGrowth(desc,subjects,milestones,now){
  var today=now;today.setHours(0,0,0,0);
  var bySubject={};
  milestones.forEach(function(ms){
    if(!bySubject[ms.subject_id])bySubject[ms.subject_id]=[];
    bySubject[ms.subject_id].push(ms);
  });
  var subjViews=[],timelines={};
  subjects.forEach(function(s){
    var bd=s.birthday?new Date(s.birthday):null;
    var age=bd?ageLabel(bd,today):null;
    var kindName=GROWTH_KIND_NAMES[s.kind]||'成长主体';
    var metaParts=[kindName];
    if(s.note)metaParts.push(s.note);
    if(age)metaParts.push(age);
    var msList=bySubject[s.id]||[];
    // 按日期倒序
    msList.sort(function(a,b){return new Date(b.happened_on)-new Date(a.happened_on);});
    var latest=msList[0];
    var milestoneStr;
    if(latest){
      var rel=daysRelLabel(daysBetween(new Date(latest.happened_on),today))||'很久以前';
      milestoneStr='最近里程碑：'+latest.title+' · '+rel;
    } else milestoneStr='还没有里程碑，记录第一条吧';
    subjViews.push({id:s.id,name:s.name,icon:GROWTH_KIND_ICONS[s.kind]||'baby',kind:s.kind,meta:metaParts.join(' · '),milestone:milestoneStr});
    var subtitle;
    if(bd&&s.birth_label)subtitle=age+' · '+s.birth_label;
    else if(bd)subtitle=age+' · 出生于'+fmtDate(bd);
    else subtitle=s.birth_label||s.name;
    timelines[s.name]={id:s.id,subtitle:subtitle,
      milestones:msList.map(function(ms){
        var d=new Date(ms.happened_on);
        var dateLabel=fmtDateShort(d);
        var rel=daysRelLabel(daysBetween(d,today));
        if(rel)dateLabel+=' · '+rel;
        return {id:ms.id,mid:ms.memory_id,date:dateLabel,title:ms.title,desc:ms.content||'',major:ms.is_major,pic:ms.has_pic,go:ms.memory_id!=null};
      })
    };
  });
  return {desc:desc,subjects:subjViews,timelines:timelines};
}

/* 时间线节点 */
function engagementCounts(){
  return Promise.all([txGetAll('perspectives'),txGetAll('comments')]).then(function(res){
    var pc={},cc={};
    res[0].forEach(function(p){if(!p.deleted_at)pc[p.memory_id]=(pc[p.memory_id]||0)+1;});
    res[1].forEach(function(c){if(!c.deleted_at)cc[c.memory_id]=(cc[c.memory_id]||0)+1;});
    return {pcounts:pc,ccounts:cc};
  });
}
function buildTimelineView(tpl,nodes,now,ec){
  var result=JSON.parse(JSON.stringify(tpl));
  result.nodes=nodes.map(function(n){
    var parts=[];
    if(n.date_str)parts.push(n.date_str);
    if(n.memory_id!=null){
      var pc=ec.pcounts[n.memory_id]||0,cc=ec.ccounts[n.memory_id]||0;
      var hints=[];
      if(pc>1)hints.push(pc+'视角');
      if(cc>0)hints.push(cc+'留言');
      if(hints.length)parts.push(hints.join(' · '));
    } else if(n.badge_hint)parts.push(n.badge_hint);
    return {k:n.node_key,mid:n.memory_id,icon:n.icon,n:n.title,d:parts.join(' · '),s:n.desc||'',node:[n.node_x,n.node_y],label:[n.label_x,n.label_y],latest:n.is_latest};
  });
  return result;
}
function buildInvites(tpl,members){
  var inv=JSON.parse(JSON.stringify(tpl));
  inv.couple.pending=members.filter(function(m){return m.space==='couple';}).map(function(m){return {id:m.id,name:m.name,avatar:m.avatar||m.name.slice(0,1),bg:m.bg,state:m.state,note:m.note};});
  inv.friend.members=members.filter(function(m){return m.space==='friend';}).map(function(m){return {id:m.id,name:m.name,avatar:m.avatar||m.name.slice(0,1),bg:m.bg,state:m.state,note:m.note};});
  return inv;
}
function buildTimelineHub(tplHub,coupleTpl,friendTpl,coupleNodes,friendNodes,memories,growthSubs,growthMs){
  var hub=JSON.parse(JSON.stringify(tplHub));
  var coupleCount=memories.filter(function(m){return m.scene==='couple';}).length;
  var friendCount=memories.filter(function(m){return m.scene==='friend';}).length;
  var latestC=coupleNodes.length?coupleNodes.reduce(function(a,b){return b.sort_order>a.sort_order?b:a;}):null;
  var latestF=friendNodes.length?friendNodes.reduce(function(a,b){return b.sort_order>a.sort_order?b:a;}):null;
  var gSubs=growthSubs||[];
  var gMs=growthMs||[];
  var latestMs=gMs.length?gMs.reduce(function(a,b){return new Date(b.created_at)>new Date(a.created_at)?b:a;}):null;
  (hub.cards||[]).forEach(function(card){
    if(card.type==='couple'){
      card.meta='情侣时间轴 · '+coupleCount+' 条记忆 · 1对1共建';
      card.last=latestC?'最近：'+latestC.title+' · 今天':'最近：暂无节点';
    } else if(card.type==='friend'){
      card.meta='友情时间轴 · 1人共建 · '+friendCount+' 条记忆';
      card.last=latestF?'最近：'+latestF.title+' · 今天':'最近：暂无节点';
    } else if(card.type==='growth'){
      card.meta='成长时间轴 · '+gSubs.length+' 个独立主体';
      card.last=latestMs?'最近里程碑：'+latestMs.title:'最近里程碑：暂无';
    }
  });
  return hub;
}

/* ---------- Bootstrap 聚合（对齐 compose_bootstrap） ---------- */
function composeBootstrap(owner,user){
  var nowD=new Date();
  var data=JSON.parse(JSON.stringify(TEMPLATE));
  var _gSubs=[],_gMs=[];
  return txGetAll('memories').then(function(allMems){
    // 过滤未删除 + owner 可见
    var memories=allMems.filter(function(m){
      return !m.deleted_at&&(m.owner_id===SEED_OWNER||m.owner_id===owner);
    });
    // 按时间倒序
    memories.sort(function(a,b){
      var da=a.precise_at?new Date(a.precise_at):null;
      var db=b.precise_at?new Date(b.precise_at):null;
      if(da&&db)return db-da;
      if(da&&!db)return -1;
      if(!da&&db)return 1;
      return new Date(b.created_at)-new Date(a.created_at);
    });
    return engagementCounts().then(function(ec){
      data.home.timeline=buildTimeline(memories,nowD,ec.pcounts,ec.ccounts);
      data.home.sceneView=buildSceneView(memories,nowD,ec.pcounts,ec.ccounts);
      data.otd=buildOtd(data.otd||{},memories,nowD);
      return txGetAll('anniversaries');
    }).then(function(allAnnivs){
      var annivs=allAnnivs.filter(function(a){return !a.deleted_at&&(a.owner_id===SEED_OWNER||a.owner_id===owner);});
      annivs.sort(function(a,b){return new Date(a.created_at)-new Date(b.created_at);});
      return annivCoverMap(annivs).then(function(cmap){
        data.anniversaries=buildAnniversaries(annivs,nowD,cmap);
        return Promise.all([txGetAll('growth_subjects'),txGetAll('growth_milestones')]);
      });
    }).then(function(res){
      var subs=res[0].filter(function(s){return !s.deleted_at&&(s.owner_id===SEED_OWNER||s.owner_id===owner);});
      var ms=res[1].filter(function(m){return !m.deleted_at&&(m.owner_id===SEED_OWNER||m.owner_id===owner);});
      var desc=(data.growth||{}).desc||'为宝宝和宠物分别建立独立成长时间轴';
      data.growth=buildGrowth(desc,subs,ms,nowD);
      _gSubs=subs;_gMs=ms;   /* 暂存供 timelineHub 使用 */
      return txGetAll('timeline_nodes');
    }).then(function(allNodes){
      var nodes=allNodes.filter(function(n){return !n.deleted_at&&(n.owner_id===SEED_OWNER||n.owner_id===owner);});
      nodes.sort(function(a,b){return a.sort_order-b.sort_order;});
      var couple=nodes.filter(function(n){return n.kind==='couple';});
      var friend=nodes.filter(function(n){return n.kind==='friend';});
      return engagementCounts().then(function(ec){
        data.coupleTimeline=buildTimelineView(data.coupleTimeline||{},couple,nowD,ec);
        data.friendTimeline=buildTimelineView(data.friendTimeline||{},friend,nowD,ec);
        return txGetAll('invite_members');
      }).then(function(allMembers){
        var members=allMembers.filter(function(m){return !m.deleted_at&&(m.owner_id===SEED_OWNER||m.owner_id===owner);});
        members.sort(function(a,b){return a.sort_order-b.sort_order;});
        data.invites=buildInvites(data.invites||{},members);
        // timelineHub
        var allMems2=allNodes; // 用已加载的
        return txGetAll('memories');
      }).then(function(allMems){
        var visibleMems=allMems.filter(function(m){return !m.deleted_at&&(m.owner_id===SEED_OWNER||m.owner_id===owner);});
        var nodes2=allNodes.filter(function(n){return !n.deleted_at&&(n.owner_id===SEED_OWNER||n.owner_id===owner);});
        var coupleN=nodes2.filter(function(n){return n.kind==='couple';});
        var friendN=nodes2.filter(function(n){return n.kind==='friend';});
        data.timelineHub=buildTimelineHub(data.timelineHub||{},data.coupleTimeline||{},data.friendTimeline||{},coupleN,friendN,visibleMems,_gSubs,_gMs);
      });
    }).then(function(){
      data.timeSettings.now.label='现在 · '+(nowD.getMonth()+1)+'月'+nowD.getDate()+'日 '+fmtHM(nowD);
      // v0.9.3：时间滚轮默认值取当前本地时间，年份数组动态生成（近 8 年，含今年）
      if(!data.timeSettings.wheels)data.timeSettings.wheels={};
      data.timeSettings.wheels.years=[];
      for(var yy=nowD.getFullYear()-7;yy<=nowD.getFullYear();yy++)data.timeSettings.wheels.years.push(String(yy));
      if(!data.timeSettings.wheels.dayCount)data.timeSettings.wheels.dayCount=31;
      data.timeSettings.wheels.default={
        year:String(nowD.getFullYear()),month:(nowD.getMonth()+1)+'月',day:String(nowD.getDate()),
        hour:pad2(nowD.getHours())+':00',minute:pad2(nowD.getMinutes())
      };
      // v0.9.3：清除模板演示假数据 —— 共建时间线 pair/group 头卡换中性占位，徽章坐标清空
      if(data.coupleTimeline){
        data.coupleTimeline.pair={
          left:{name:'我',avatar:'我'},right:{name:'待邀请',avatar:'邀',bg:'#F2EBE3'},
          title:'情侣时间线',sub:'邀请一位伙伴，共建专属时间线',badge:'待共建'
        };
        data.coupleTimeline.multiViewBadges=[];
        data.coupleTimeline.commentBadges=[];
      }
      if(data.friendTimeline){
        data.friendTimeline.group={
          avatars:[{t:'我'}],more:0,
          title:'友情时间线',sub:'邀请最多 5 位好友，共建群组记忆线',badge:'待共建'
        };
        data.friendTimeline.multiViewBadges=[];
        data.friendTimeline.commentBadges=[];
      }
      data.meta.note='本地模式 · IndexedDB · '+memories.length+' 条记忆';
      data.meta.apiToken='local-mode';
      data.meta.auth={loggedIn:!!user,owner:owner,user:user?{id:user.id,username:user.username,nickname:user.nickname,avatar:user.avatar}:null};
      data.meta.version='3.3';
      return Promise.all([getOrCreateInviteCode('couple'),getOrCreateInviteCode('friend')]).then(function(codes){
        data.invites.couple.inviteCode=codes[0];
        data.invites.friend.inviteCode=codes[1];
        return data;
      });
    });
  });
}

/* ---------- 认证（简化版） ---------- */
function hashPassword(password){
  // 简化：用 SHA-256（Web Crypto API）
  return crypto.subtle.digest('SHA-256',new TextEncoder().encode(password+'::mv_salt')).then(function(buf){
    return Array.from(new Uint8Array(buf)).map(function(b){return b.toString(16).padStart(2,'0');}).join('');
  });
}
function register(username,password,nickname){
  return txGetAllByIndex('users','username',username).then(function(existing){
    if(existing.length)throw{status:409,message:'用户名已存在'};
    return hashPassword(password);
  }).then(function(hash){
    return getNextId('users').then(function(id){
      var u={id:id,username:username,password_hash:hash,nickname:nickname||username,avatar:null,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),deleted_at:null};
      return txPut('users',u).then(function(){return u;});
    });
  }).then(function(u){
    return createSession(u).then(function(token){
      return {token:token,user:{id:u.id,username:u.username,nickname:u.nickname,avatar:u.avatar}};
    });
  });
}
function login(username,password){
  return txGetAllByIndex('users','username',username).then(function(users){
    if(!users.length)throw{status:401,message:'用户名或密码错误'};
    var u=users[0];
    return hashPassword(password).then(function(hash){
      if(hash!==u.password_hash)throw{status:401,message:'用户名或密码错误'};
      return createSession(u).then(function(token){
        return {token:token,user:{id:u.id,username:u.username,nickname:u.nickname,avatar:u.avatar}};
      });
    });
  });
}
function createSession(user){
  var token=randomHex(32);
  var expires=new Date();expires.setDate(expires.getDate()+30);
  return txPut('sessions',{token:token,user_id:user.id,expires_at:expires.toISOString()}).then(function(){return token;});
}
function getSessionUser(token){
  if(!token)return Promise.resolve(null);
  return txGet('sessions',token).then(function(s){
    if(!s)return null;
    if(new Date(s.expires_at)<new Date())return null;
    return txGet('users',s.user_id).then(function(u){
      if(!u||u.deleted_at)return null;
      return u;
    });
  });
}
function logout(token){
  return txDelete('sessions',token).then(function(){return true;});
}
function getOrCreateInviteCode(space){
  var key='invite_'+space+'_code';
  return txGet('meta',key).then(function(v){
    if(v&&v.value)return v.value;
    var code='MV'+randomHex(6).toUpperCase();
    return txPut('meta',{key:key,value:code}).then(function(){return code;});
  });
}

/* ---------- Mock Response 工厂 ---------- */
function mockResponse(data,status){
  status=status||200;
  var body=JSON.stringify({ok:status<400,data:data});
  return {
    ok:status<400,status:status,
    json:function(){return Promise.resolve(JSON.parse(body));},
    text:function(){return Promise.resolve(body);}
  };
}
function mockRawResponse(data,status){
  /* bootstrap 端点返回裸数据（不包 {ok,data}），与 Python 一致 */
  status=status||200;
  var body=JSON.stringify(data);
  return {
    ok:status<400,status:status,
    json:function(){return Promise.resolve(typeof data==='object'?data:JSON.parse(body));},
    text:function(){return Promise.resolve(body);}
  };
}
function mockError(status,message){
  return mockResponse({message:message},status);
}

/* ---------- 本地 API 路由器（替换 fetch） ---------- */
function localApiRouter(url,opts){
  opts=opts||{};
  var method=(opts.method||'GET').toUpperCase();
  var body=opts.body?JSON.parse(opts.body):{};
  // 解析路径
  var path=url.split('?')[0];
  var qs={};
  var qm=url.split('?')[1];
  if(qm)qm.split('&').forEach(function(p){var kv=p.split('=');qs[kv[0]]=decodeURIComponent(kv[1]||'');});

  // 解析身份
  var authHeader=(opts.headers||{})['Authorization']||'';
  var token=authHeader.startsWith('Bearer ')?authHeader.slice(7):'';

  // ===== 路由 =====

  // bootstrap
  if(path==='/api/app/bootstrap'&&method==='GET'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return composeBootstrap(owner,user);
    }).then(function(data){return mockRawResponse(data);});
  }
  if(path==='/api/app/bootstrap'&&method==='POST'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return composeBootstrap(owner,user);
    }).then(function(data){return mockRawResponse(data);});
  }

  // auth
  if(path==='/api/auth/register'&&method==='POST'){
    return register(body.username,body.password,body.nickname).then(function(r){
      return mockResponse(r,201);
    }).catch(function(e){return mockError(e.status||500,e.message||'注册失败');});
  }
  if(path==='/api/auth/login'&&method==='POST'){
    return login(body.username,body.password).then(function(r){
      return mockResponse(r);
    }).catch(function(e){return mockError(e.status||500,e.message||'登录失败');});
  }
  if(path==='/api/auth/logout'&&method==='POST'){
    return logout(token).then(function(){return mockResponse({});});
  }
  if(path==='/api/auth/me'&&method==='GET'){
    return getSessionUser(token).then(function(u){
      if(!u)return mockError(401,'未登录');
      return mockResponse({id:u.id,username:u.username,nickname:u.nickname,avatar:u.avatar});
    });
  }

  // memories
  if(path==='/api/v1/memories'&&method==='GET'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return txGetAll('memories');
    }).then(function(all){
      var mems=all.filter(function(m){return !m.deleted_at&&(m.owner_id===SEED_OWNER||m.owner_id===owner);});
      return engagementCounts().then(function(ec){
        return mockResponse(mems.map(function(m){
          return {
            id:m.id,scene:m.scene,feel:m.feel,emotions:m.emotions||[],voice:m.voice,
            timestampType:m.timestamp_type,
            preciseAt:m.precise_at?m.precise_at.replace('T',' ').slice(0,16):null,
            fuzzyLabel:m.fuzzy_label,fuzzyNote:m.fuzzy_note,
            media:(m.media||[]).map(function(c){return {key:c.key,url:resolveFileUrl(c.key),kind:c.kind};}),
            source:m.source,perspectiveCount:ec.pcounts[m.id]||0,commentCount:ec.ccounts[m.id]||0
          };
        }));
      });
    });
  }
  if(path==='/api/v1/memories'&&method==='POST'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return getNextId('memories').then(function(id){
        var nowISO=new Date().toISOString();
        /* 时间戳归一化（对齐 main.py）：
         * fuzzy → precise_at=null，label/note 落库；
         * now → 当前本地时间；custom → custom_date+custom_time 组合（缺省回落当前值） */
        var preciseAt=null,fuzzyLabel=null,fuzzyNote=null;
        if(body.time_mode==='fuzzy'){
          fuzzyLabel=(body.fuzzy_label||'').trim()||'记不清了';
          fuzzyNote=(body.fuzzy_note||'').trim()||null;
        }else{
          var d=new Date();
          if(body.time_mode==='custom'){
            var ds=String(body.custom_date||'').split('-');
            if(ds.length===3)d=new Date(+ds[0],+ds[1]-1,+ds[2]);
            var ts=String(body.custom_time||'').split(':');
            if(ts.length>=2){d.setHours(+ts[0]);d.setMinutes(+ts[1]);}
          }
          preciseAt=d.toISOString();
        }
        var mediaItems=(body.media||[]).map(function(f){
          var key=f.file_key||f.key;
          return {key:key,url:resolveFileUrl(key),kind:key.split('.').pop()};
        });
        var m={
          id:id,scene:body.scene||'personal',feel:body.feel||'无',
          emotions:body.emotion?[body.emotion]:[],
          voice:body.voice||null,timestamp_type:body.time_mode==='fuzzy'?'fuzzy':'precise',
          precise_at:preciseAt,fuzzy_label:fuzzyLabel,
          fuzzy_note:fuzzyNote,meta_override:null,media:mediaItems,source:'user',owner_id:owner,
          created_at:nowISO,updated_at:nowISO,deleted_at:null
        };
        return txPut('memories',m).then(function(){return mockResponse({id:m.id,scene:m.scene,feel:m.feel},201);});
      });
    });
  }
  // memory detail
  var mMatch=/^\/api\/v1\/memories\/(\d+)$/.exec(path);
  if(mMatch){
    var mid=+mMatch[1];
    if(method==='GET'){
      return txGet('memories',mid).then(function(m){
        if(!m||m.deleted_at)return mockError(404,'记忆不存在');
        return Promise.all([
          txGetAllByIndex('perspectives','memory_id',mid),
          txGetAllByIndex('comments','memory_id',mid)
        ]).then(function(results){
          var persps=results[0],cmts=results[1];
          var perspView=persps.filter(function(p){return !p.deleted_at;}).map(function(p){
            var pd=new Date(p.created_at);
            return {id:p.id,name:p.author_name,avatar:p.author_avatar||p.author_name.slice(0,1),bg:p.author_bg,feel:p.feel,time:(pd.getMonth()+1)+'月'+pd.getDate()+'日 '+fmtHM(pd)};
          });
          var cmtsView=cmts.filter(function(c){return !c.deleted_at;}).map(function(c){
            var cd=new Date(c.created_at);
            return {id:c.id,name:c.author_name,avatar:c.author_avatar||c.author_name.slice(0,1),bg:c.author_bg,content:c.content,time:(cd.getMonth()+1)+'月'+cd.getDate()+'日 '+fmtHM(cd)};
          });
          return mockResponse({
            id:m.id,scene:m.scene,feel:m.feel,emotions:m.emotions||[],voice:m.voice,
            timestampType:m.timestamp_type,
            preciseAt:m.precise_at?m.precise_at.replace('T',' ').slice(0,16):null,
            fuzzyLabel:m.fuzzy_label,fuzzyNote:m.fuzzy_note,
            media:(m.media||[]).map(function(c){return {key:c.key,url:resolveFileUrl(c.key),kind:c.kind};}),
            source:m.source,timeLabel:fmtMemoryDate(m,new Date()),
            perspectives:perspView,comments:cmtsView
          });
        });
      });
    }
    if(method==='PATCH'){
      return getSessionUser(token).then(function(user){
        var owner=user?'user:'+user.id:LOCAL_OWNER;
        return txGet('memories',mid);
      }).then(function(m){
        if(!m||m.deleted_at)return mockError(404,'记忆不存在');
        if(body.scene)m.scene=body.scene;
        if(body.feel)m.feel=body.feel;
        if(body.emotions!==undefined)m.emotions=body.emotions;
        if(body.media!==undefined)m.media=body.media.map(function(f){return {key:f.file_key||f.key,url:resolveFileUrl(f.file_key||f.key),kind:(f.file_key||f.key).split('.').pop()};});
        m.updated_at=new Date().toISOString();
        return txPut('memories',m).then(function(){return mockResponse({id:m.id});});
      });
    }
    if(method==='DELETE'){
      return txGet('memories',mid).then(function(m){
        if(!m||m.deleted_at)return mockError(404,'记忆不存在');
        m.deleted_at=new Date().toISOString();
        return txPut('memories',m).then(function(){
          /* v0.9.4：级联软删除关联的纪念日（记忆删了，纪念日不该残留成示例） */
          return txGetAll('anniversaries').then(function(all){
            var tasks=all.filter(function(a){return a.linked_memory_id===mid&&!a.deleted_at;}).map(function(a){
              a.deleted_at=new Date().toISOString();
              return txPut('anniversaries',a);
            });
            return Promise.all(tasks).then(function(){return mockResponse({});});
          });
        });
      });
    }
  }
  // perspectives
  var pMatch=/^\/api\/v1\/memories\/(\d+)\/perspectives$/.exec(path);
  if(pMatch&&method==='GET'){
    return txGetAllByIndex('perspectives','memory_id',+pMatch[1]).then(function(all){
      return mockResponse(all.filter(function(p){return !p.deleted_at;}).map(function(p){
        var pd=new Date(p.created_at);
        return {id:p.id,name:p.author_name,avatar:p.author_avatar||p.author_name.slice(0,1),bg:p.author_bg,feel:p.feel,time:(pd.getMonth()+1)+'月'+pd.getDate()+'日 '+fmtHM(pd)};
      }));
    });
  }
  if(pMatch&&method==='POST'){
    return getNextId('perspectives').then(function(id){
      var nowISO=new Date().toISOString();
      return txPut('perspectives',{id:id,memory_id:+pMatch[1],author_name:body.author_name||'我',author_avatar:body.author_avatar||null,author_bg:body.author_bg||null,feel:body.feel||'',created_at:nowISO,updated_at:nowISO,deleted_at:null}).then(function(){return mockResponse({id:id},201);});
    });
  }
  var pdMatch=/^\/api\/v1\/perspectives\/(\d+)$/.exec(path);
  if(pdMatch&&method==='DELETE'){
    return txGet('perspectives',+pdMatch[1]).then(function(p){
      if(!p)return mockError(404,'视角不存在');
      p.deleted_at=new Date().toISOString();
      return txPut('perspectives',p).then(function(){return mockResponse({});});
    });
  }
  // comments
  var cMatch=/^\/api\/v1\/memories\/(\d+)\/comments$/.exec(path);
  if(cMatch&&method==='GET'){
    return txGetAllByIndex('comments','memory_id',+cMatch[1]).then(function(all){
      return mockResponse(all.filter(function(c){return !c.deleted_at;}).map(function(c){
        var cd=new Date(c.created_at);
        return {id:c.id,name:c.author_name,avatar:c.author_avatar||c.author_name.slice(0,1),bg:c.author_bg,content:c.content,time:(cd.getMonth()+1)+'月'+cd.getDate()+'日 '+fmtHM(cd)};
      }));
    });
  }
  if(cMatch&&method==='POST'){
    return getNextId('comments').then(function(id){
      var nowISO=new Date().toISOString();
      return txPut('comments',{id:id,memory_id:+cMatch[1],author_name:body.author_name||'我',author_avatar:body.author_avatar||null,author_bg:body.author_bg||null,content:body.content||'',created_at:nowISO,updated_at:nowISO,deleted_at:null}).then(function(){return mockResponse({id:id},201);});
    });
  }
  var cdMatch=/^\/api\/v1\/comments\/(\d+)$/.exec(path);
  if(cdMatch&&method==='DELETE'){
    return txGet('comments',+cdMatch[1]).then(function(c){
      if(!c)return mockError(404,'留言不存在');
      c.deleted_at=new Date().toISOString();
      return txPut('comments',c).then(function(){return mockResponse({});});
    });
  }
  // anniversaries
  if(path==='/api/v1/anniversaries'&&method==='GET'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return composeBootstrap(owner,user);
    }).then(function(data){return mockResponse(data.anniversaries);});
  }
  if(path==='/api/v1/anniversaries'&&method==='POST'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return getNextId('anniversaries').then(function(id){
        var nowISO=new Date().toISOString();
        var a={id:id,owner_id:owner,name:body.name||'纪念日',month:body.month||1,day:body.day||1,is_lunar:!!body.is_lunar,lunar_label:body.lunar_label||null,is_recurring:body.is_recurring!==false,remind_days_before:body.remind_days_before||3,note:body.note||null,linked_memory_id:body.linked_memory_id||null,source:'user',created_at:nowISO,updated_at:nowISO,deleted_at:null};
        return txPut('anniversaries',a).then(function(){return mockResponse({id:id},201);});
      });
    });
  }
  var aMatch=/^\/api\/v1\/anniversaries\/(\d+)$/.exec(path);
  if(aMatch&&method==='DELETE'){
    return txGet('anniversaries',+aMatch[1]).then(function(a){
      if(!a)return mockError(404,'纪念日不存在');
      a.deleted_at=new Date().toISOString();
      return txPut('anniversaries',a).then(function(){return mockResponse({});});
    });
  }
  if(aMatch&&method==='PATCH'){
    return txGet('anniversaries',+aMatch[1]).then(function(a){
      if(!a||a.deleted_at)return mockError(404,'纪念日不存在');
      ['name','month','day','is_lunar','lunar_label','is_recurring','remind_days_before','note','linked_memory_id'].forEach(function(k){
        if(body[k]!==undefined)a[k]=body[k];
      });
      a.updated_at=new Date().toISOString();
      return txPut('anniversaries',a).then(function(){return mockResponse({id:a.id});});
    });
  }
  // growth
  if(path==='/api/v1/growth/subjects'&&method==='GET'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return composeBootstrap(owner,user);
    }).then(function(data){return mockResponse(data.growth.subjects);});
  }
  if(path==='/api/v1/growth/subjects'&&method==='POST'){
    return getNextId('growth_subjects').then(function(id){
      var nowISO=new Date().toISOString();
      var s={id:id,owner_id:LOCAL_OWNER,name:body.name||'成长主体',kind:body.kind||'baby',birthday:body.birthday||null,birth_label:body.birth_label||null,note:body.note||null,source:'user',created_at:nowISO,updated_at:nowISO,deleted_at:null};
      return txPut('growth_subjects',s).then(function(){return mockResponse({id:id},201);});
    });
  }
  var gsMatch=/^\/api\/v1\/growth\/subjects\/(\d+)$/.exec(path);
  if(gsMatch&&method==='DELETE'){
    return txGet('growth_subjects',+gsMatch[1]).then(function(s){
      if(!s)return mockError(404,'主体不存在');
      s.deleted_at=new Date().toISOString();
      return txPut('growth_subjects',s).then(function(){
        return txGetAllByIndex('growth_milestones','subject_id',+gsMatch[1]);
      }).then(function(ms){
        return Promise.all(ms.map(function(m){m.deleted_at=new Date().toISOString();return txPut('growth_milestones',m);}));
      }).then(function(){return mockResponse({});});
    });
  }
  var gmsMatch=/^\/api\/v1\/growth\/subjects\/(\d+)\/milestones$/.exec(path);
  if(gmsMatch&&method==='POST'){
    return getNextId('growth_milestones').then(function(id){
      var nowISO=new Date().toISOString();
      var m={id:id,subject_id:+gmsMatch[1],memory_id:body.memory_id||null,title:body.title||'里程碑',content:body.content||null,happened_on:body.happened_on||nowISO,is_major:!!body.is_major,has_pic:!!body.has_pic,owner_id:LOCAL_OWNER,source:'user',created_at:nowISO,updated_at:nowISO,deleted_at:null};
      return txPut('growth_milestones',m).then(function(){return mockResponse({id:id},201);});
    });
  }
  var gmMatch=/^\/api\/v1\/growth\/milestones\/(\d+)$/.exec(path);
  if(gmMatch&&method==='DELETE'){
    return txGet('growth_milestones',+gmMatch[1]).then(function(m){
      if(!m)return mockError(404,'里程碑不存在');
      m.deleted_at=new Date().toISOString();
      return txPut('growth_milestones',m).then(function(){return mockResponse({});});
    });
  }
  // invite members：添加成员（邀请/接受共用，本地模拟共建）
  if(path==='/api/v1/invites/members'&&method==='POST'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return getNextId('invite_members').then(function(id){
        var name=(body.name||'').trim()||'伙伴';
        var nowISO=new Date().toISOString();
        var m={id:id,space:body.space||'couple',name:name,avatar:name.slice(0,1),bg:body.bg||null,state:body.state||'待接受',note:body.note||null,sort_order:0,source:'user',owner_id:owner,created_at:nowISO,updated_at:nowISO,deleted_at:null};
        return txPut('invite_members',m).then(function(){return mockResponse(m,201);});
      });
    });
  }
  // 接受邀请：输入邀请码加入共建（本地模拟，标记「已加入」）
  if(path==='/api/v1/invites/accept'&&method==='POST'){
    return getSessionUser(token).then(function(user){
      var owner=user?'user:'+user.id:LOCAL_OWNER;
      return getNextId('invite_members').then(function(id){
        var name=(body.name||'').trim()||'伙伴';
        var nowISO=new Date().toISOString();
        var m={id:id,space:body.space||'couple',name:name,avatar:name.slice(0,1),bg:null,state:'已加入',note:body.note||null,sort_order:0,source:'user',owner_id:owner,created_at:nowISO,updated_at:nowISO,deleted_at:null};
        return txPut('invite_members',m).then(function(){return mockResponse(m,201);});
      });
    });
  }
  var imMatch=/^\/api\/v1\/invites\/members\/(\d+)$/.exec(path);
  if(imMatch&&method==='DELETE'){
    return txGet('invite_members',+imMatch[1]).then(function(m){
      if(!m)return mockError(404,'成员不存在');
      m.deleted_at=new Date().toISOString();
      return txPut('invite_members',m).then(function(){return mockResponse({});});
    });
  }
  // uploads: presign
  if(path==='/api/v1/uploads/presign'&&method==='POST'){
    var ext=(body.filename||'').toLowerCase().match(/\.([a-z0-9]+)$/);
    ext=ext?ext[1]:'';
    if(!ALLOWED_EXT[ext])return Promise.resolve(mockError(422,'不支持的文件类型: .'+ext));
    var fileKey=genFileKey(ext);
    return Promise.resolve(mockResponse({
      fileKey:fileKey,uploadUrl:'local-upload:'+fileKey,method:'PUT',
      headers:{'Content-Type':body.contentType||'application/octet-stream'},
      contentType:body.contentType||'application/octet-stream',
      expiresAt:Math.floor(Date.now()/1000)+3600
    },201));
  }
  // media attach
  var maMatch=/^\/api\/v1\/memories\/(\d+)\/media$/.exec(path);
  if(maMatch&&method==='POST'){
    var mid2=+maMatch[1];
    return txGet('memories',mid2).then(function(m){
      if(!m||m.deleted_at)return mockError(404,'记忆不存在');
      var key=body.file_key;
      var item={key:key,url:resolveFileUrl(key),kind:key.split('.').pop()};
      m.media=m.media||[];m.media.push(item);
      m.updated_at=new Date().toISOString();
      return txPut('memories',m).then(function(){return mockResponse({memoryId:mid2,media:m.media},201);});
    });
  }

  // 默认：未匹配
  console.warn('[localdb] 未匹配的路由:',method,path);
  return Promise.resolve(mockError(404,'Not Found: '+path));
}

/* ---------- 本地上传处理器 ---------- */
function localUploadRouter(url,opts){
  opts=opts||{};
  var m=/^local-upload:([0-9a-f]{24}\.[a-z0-9]+)$/.exec(url);
  if(!m)return Promise.resolve(mockError(400,'Invalid upload URL'));
  var key=m[1];
  var body=opts.body;
  // body 可能是 File/Blob/ArrayBuffer
  var blobPromise;
  if(body instanceof Blob){blobPromise=Promise.resolve(body);}
  else if(body instanceof ArrayBuffer){blobPromise=Promise.resolve(new Blob([body]));}
  else if(body&&typeof body==='object'&&body.arrayBuffer){blobPromise=body.arrayBuffer().then(function(ab){return new Blob([ab]);});}
  else{blobPromise=Promise.resolve(new Blob([body||'']));}
  return blobPromise.then(function(blob){
    return storeBlob(key,blob);
  }).then(function(blobUrl){
    return mockResponse({fileKey:key,url:blobUrl});
  });
}

/* ---------- 初始化 ---------- */
function init(){
  return openDB().then(function(){
    return loadTemplate();
  }).then(function(tpl){
    TEMPLATE=tpl;
    return purgeSeeds();   /* v0.9.3：清除历史版本导入的种子假数据，不再导入 */
  }).then(function(){
    return loadAllBlobs();
  }).then(function(){
    // 安装 fetch 拦截
    var origFetch=window.fetch;
    window.fetch=function(url,opts){
      if(typeof url==='string'){
        // 本地 API 路由
        if(url.indexOf('/api/')===0||url.indexOf('/api/app/')===0){
          return localApiRouter(url,opts).catch(function(e){
            console.error('[localdb] API error:',e);
            return mockError(500,e.message||'Internal Error');
          });
        }
        // 本地上传
        if(url.indexOf('local-upload:')===0){
          return localUploadRouter(url,opts);
        }
      }
      // 其他请求走原始 fetch
      return origFetch.apply(window,arguments);
    };
    console.log('[localdb] 初始化完成，fetch 拦截已安装');
    return true;
  });
}

/* ---------- 清空全部数据 ---------- */
function clearAll(){
  var stores=['memories','perspectives','comments','anniversaries',
    'growth_subjects','growth_milestones','timeline_nodes','invite_members',
    'users','sessions','files','meta'];
  return openDB().then(function(db){
    var tx=db.transaction(stores,'readwrite');
    stores.forEach(function(s){
      tx.objectStore(s).clear();
    });
    return new Promise(function(res,rej){
      tx.oncomplete=function(){res();};
      tx.onerror=function(){rej(tx.error);};
    });
  }).then(function(){
    console.log('[localdb] 全部数据已清空');
    // 重新加载页面以重新初始化
    location.reload();
  });
}

/* ---------- 导出 ---------- */
window.__localdb={init:init,reload:function(){
  return purgeSeeds().then(function(){return loadAllBlobs();});
},clearAll:clearAll};

})();
