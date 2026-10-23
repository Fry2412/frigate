(() => {
  let token = "";
  const el = (id) => document.getElementById(id);
  const message = (text, error = false) => { el("message").textContent = text; el("message").classList.toggle("error", error); };
  const request = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(url, {...options, headers});
    if (!response.ok) {
      if (response.status === 204) return null;
      let detail = `Request failed (${response.status})`;
      try { const body = await response.json(); detail = body.detail || detail; } catch {}
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/zip") || contentType.startsWith("image/") ? response.blob() : response.json();
  };
  const node = (tag, text, className) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; };

  el("connect").addEventListener("click", async () => {
    token = el("token").value;
    try { await loadImages(); await loadJobs(); el("connection").textContent = "Connected"; message("Connected to manager."); }
    catch (error) { token = ""; el("connection").textContent = "Disconnected"; message(error.message, true); }
  });
  el("refresh").addEventListener("click", async () => { try { await loadImages(); await loadJobs(); message("Updated."); } catch (error) { message(error.message, true); } });
  el("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const camera = el("camera").value.trim();
      for (const file of el("files").files) {
        const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
        await request("/api/v1/images", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({camera, image_base64:encoded})});
      }
      el("upload-form").reset(); await loadImages(); message("Images uploaded.");
    } catch (error) { message(error.message, true); }
  });
  el("job-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const body = {classes:el("classes").value.split(",").map((name) => name.trim()).filter(Boolean), epochs:Number(el("epochs").value), batch_size:Number(el("batch").value), image_size:Number(el("image-size").value)};
      const job = await request("/api/v1/jobs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
      await loadJobs(); message(`Job ${job.id} queued.`);
    } catch (error) { message(error.message, true); }
  });

  async function loadImages() {
    const images = await request("/api/v1/images");
    const grid = el("images"); grid.replaceChildren();
    if (!images.length) { grid.append(node("p", "No images yet.", "empty")); return; }
    for (const image of images) grid.append(await makeImageCard(image));
  }
  async function makeImageCard(image) {
    const card = node("article", undefined, "image-card");
    const meta = node("div", undefined, "image-meta"); meta.append(node("strong", `${image.camera} · ${image.width}×${image.height}`), node("span", image.verified ? "Reviewed" : "Needs review", `status${image.verified ? " verified" : ""}`)); card.append(meta);
    const wrap = node("div", undefined, "canvas-wrap"); const img = node("img"); img.alt = `Submitted image from ${image.camera}`;
    const imageBlob = await request(`/api/v1/images/${encodeURIComponent(image.id)}/file`);
    img.src = URL.createObjectURL(imageBlob); wrap.append(img); const canvas = node("canvas"); wrap.append(canvas); card.append(wrap);
    const ctx = canvas.getContext("2d"); let start = null, selected = null;
    const redraw = () => {
      const rect = canvas.getBoundingClientRect(); const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * ratio)); canvas.height = Math.max(1, Math.round(rect.height * ratio)); ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
      for (const annotation of image.annotations) drawBox(annotation.bbox, annotation.negative ? "#db654d" : "#20a478");
      if (selected) drawBox(selected, "#efab37");
    };
    const drawBox = (box, color) => { const rect = canvas.getBoundingClientRect(); ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(box[0]*rect.width,box[1]*rect.height,box[2]*rect.width,box[3]*rect.height); };
    img.addEventListener("load", redraw); new ResizeObserver(redraw).observe(wrap);
    const point = (event) => { const rect=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))]; };
    canvas.addEventListener("pointerdown",(event)=>{start=point(event);canvas.setPointerCapture(event.pointerId);selected=null;});
    canvas.addEventListener("pointermove",(event)=>{if(!start)return;const end=point(event);selected=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.abs(end[0]-start[0]),Math.abs(end[1]-start[1])];redraw();});
    canvas.addEventListener("pointerup",()=>{start=null;});
    const tools = node("div", undefined, "image-tools"); const label=node("input");label.placeholder="Class name";label.maxLength=100;label.setAttribute("aria-label","Class name");
    const negativeWrap=node("label","False positive"); const negative=node("input");negative.type="checkbox";negativeWrap.append(negative);
    const save=node("button","Save box");save.type="button";save.addEventListener("click",async()=>{try{if(!selected||selected[2]<=0||selected[3]<=0)throw new Error("Draw a box first.");const result=await request(`/api/v1/images/${encodeURIComponent(image.id)}/annotations`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({label:label.value,bbox:selected,negative:negative.checked})});image.annotations.push(result);image.verified=false;selected=null;redraw();renderAnnotations(list,image,redraw);meta.lastChild.textContent="Needs review";meta.lastChild.className="status";message("Annotation saved. Review the image again.");}catch(error){message(error.message,true);}});
    tools.append(label,negativeWrap,save); card.append(tools);
    const verify=node("button",image.verified?"Reviewed":"Mark reviewed");verify.type="button";verify.classList.add("wide");verify.addEventListener("click",async()=>{try{await request(`/api/v1/images/${encodeURIComponent(image.id)}/verification`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({verified:true})});image.verified=true;meta.lastChild.textContent="Reviewed";meta.lastChild.className="status verified";message("Image marked reviewed.");}catch(error){message(error.message,true);}}); tools.append(verify);
    const list=node("ul",undefined,"annotation-list");card.append(list);renderAnnotations(list,image,redraw);
    return card;
  }
  function renderAnnotations(list,image,redraw=()=>{}){list.replaceChildren();if(!image.annotations.length){list.append(node("li","No annotations"));return;}for(const annotation of image.annotations){const li=node("li",`${annotation.label} · ${annotation.negative?"false positive":"target"}${annotation.difficult?" · difficult":""}`);const remove=node("button","Remove");remove.type="button";remove.addEventListener("click",async()=>{try{await request(`/api/v1/images/${encodeURIComponent(image.id)}/annotations/${encodeURIComponent(annotation.id)}`,{method:"DELETE"});image.annotations=image.annotations.filter((item)=>item.id!==annotation.id);image.verified=false;redraw();renderAnnotations(list,image,redraw);message("Annotation removed. Review the image again.");}catch(error){message(error.message,true);}});li.append(remove);list.append(li);}}
  async function loadJobs(){const jobs=await request("/api/v1/jobs");const box=el("jobs");box.replaceChildren();if(!jobs.length){box.append(node("p","No training jobs yet.","empty"));return;}for(const job of jobs){const row=node("div",undefined,"job-row");row.append(node("span",`${job.status.toUpperCase()} · ${job.id}${job.error?` · ${job.error}`:""}`));if(job.artifact_available){const download=node("button","Download result");download.type="button";download.addEventListener("click",async()=>{try{const blob=await request(`/api/v1/jobs/${encodeURIComponent(job.id)}/artifact`);const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`${job.id}-result.zip`;link.click();URL.revokeObjectURL(link.href);}catch(error){message(error.message,true);}});row.append(download);}box.append(row);}}
})();
