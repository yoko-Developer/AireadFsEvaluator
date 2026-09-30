from __future__ import annotations
import csv, json, logging, re, shutil
from collections import defaultdict
from pathlib import Path

TARGET_FORMIDS = {'01_010_02','01_020_02','01_030_02','01_040_02','01_050_02'}

def _fitz():
    try: import fitz; return fitz
    except ImportError as e: raise RuntimeError('複数帳票ページの分割には PyMuPDF が必要です。pip install PyMuPDF を1回実行してください。') from e

def _runs(vals):
    out=[]; start=None; vals=list(vals)
    for i,v in enumerate(vals):
        if v and start is None: start=i
        if start is not None and (not v or i==len(vals)-1):
            out.append((start, i if not v else i+1)); start=None
    return out

def _bbox(ink,x0,y0,x1,y1,margin=10):
    import numpy as np
    ys,xs=np.where(ink[y0:y1,x0:x1])
    if not len(xs): return None
    return (max(x0,x0+int(xs.min())-margin), max(y0,y0+int(ys.min())-margin),
            min(x1,x0+int(xs.max())+1+margin), min(y1,y0+int(ys.max())+1+margin))

def _detect(page):
    import numpy as np
    fitz=_fitz(); pix=page.get_pixmap(matrix=fitz.Matrix(1,1),colorspace=fitz.csGRAY,alpha=False)
    a=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width); ink=a<220
    ys,xs=np.where(ink)
    if not len(xs): return [(0,0,page.rect.width,page.rect.height)]
    bx0,bx1,by0,by1=int(xs.min()),int(xs.max())+1,int(ys.min()),int(ys.max())+1; w,h=pix.width,pix.height
    gaps=[]
    for a0,b0 in _runs(ink.sum(0)<=1):
        mid=(a0+b0)/2
        if b0-a0>=max(12,int(w*.025)) and bx0+w*.18<mid<bx1-w*.18: gaps.append((b0-a0,a0,b0))
    if gaps:
        _,a0,b0=max(gaps); cut=(a0+b0)//2
        boxes=[_bbox(ink,0,0,cut,h),_bbox(ink,cut,0,w,h)]; boxes=[b for b in boxes if b]
        if len(boxes)>1: return boxes
    gaps=[]
    for a0,b0 in _runs(ink.sum(1)<=1):
        mid=(a0+b0)/2
        if b0-a0>=max(18,int(h*.06)) and by0+h*.12<mid<by1-h*.12: gaps.append((b0-a0,a0,b0))
    if gaps:
        _,a0,b0=max(gaps); cut=(a0+b0)//2
        boxes=[_bbox(ink,0,0,w,cut),_bbox(ink,0,cut,w,h)]; boxes=[b for b in boxes if b]
        if len(boxes)>1: return boxes
    return [_bbox(ink,0,0,w,h) or (0,0,w,h)]

def _write_variant(page, rect, dest: Path, mode: str):
    fitz=_fitz(); pix=page.get_pixmap(matrix=fitz.Matrix(2,2), clip=rect, alpha=False); d=fitz.open()
    if mode == 'C':  # crop/rebase
        p=d.new_page(width=rect.width,height=rect.height); p.insert_image(p.rect,pixmap=pix)
    elif mode == 'A':  # anchored: original coordinates/page size
        p=d.new_page(width=page.rect.width,height=page.rect.height); p.insert_image(rect,pixmap=pix)
    elif mode == 'F':  # fit: isolated region scaled to original page size
        p=d.new_page(width=page.rect.width,height=page.rect.height); p.insert_image(p.rect,pixmap=pix,keep_proportion=True)
    else:
        d.close(); raise ValueError(mode)
    d.save(dest,garbage=4,deflate=True); d.close()

def split_pdf_for_airead(src:Path,outdir:Path, robust: bool=True):
    """Split physical pages into logical regions.

    robust=True emits three layout variants per region. AIRead CoordDefined behavior differs by
    template, so consolidation later chooses ONE successful variant per logical region.
    """
    fitz=_fitz(); outdir.mkdir(parents=True,exist_ok=True); doc=fitz.open(src); manifest={}
    for pi,page in enumerate(doc):
        regions=_detect(page); logging.info('  ✂ P%d: %d領域をAIReadへ投入',pi+1,len(regions))
        centers=[((b[0]+b[2])/2,(b[1]+b[3])/2) for b in regions]
        side_by_side=(len(centers)>1 and (max(x for x,_ in centers)-min(x for x,_ in centers)) > (max(y for _,y in centers)-min(y for _,y in centers)))
        for ri,coords in enumerate(regions,1):
            rect=fitz.Rect(*coords)&page.rect
            # Preferred first; robust specified-PDF run also tries fallbacks without asking user to rerun.
            modes=(('C','F','A') if side_by_side else ('A','C','F')) if robust else (('C',) if side_by_side else ('A',))
            for priority,mode in enumerate(modes):
                name=f'{src.stem}__P{pi+1:03d}R{ri:02d}V{mode}.pdf'; dest=outdir/name
                _write_variant(page,rect,dest,mode)
                manifest[dest.stem]=(src.stem,pi,ri,mode,priority)
            logging.info('    P%d 帳票%d variants=%s',pi+1,ri,'/'.join(modes))
    doc.close(); return manifest

def _normalize_formid(fid: str) -> str:
    fid=(fid or '').strip(); m=re.match(r'^(\d{2}_\d{3}_\d{2})(?:_\d+)?$',fid)
    return m.group(1) if m else fid

def _read_ids(path:Path):
    ids=[]
    if path.exists():
        with path.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                fid=_normalize_formid(r.get('formid') or '')
                if fid: ids.append(fid)
    return ids

def consolidate_airead_outputs(outdir:Path,manifest:dict):
    if not outdir.exists(): raise RuntimeError(f'AIRead output フォルダがありません: {outdir}')
    # Find every produced variant.
    produced={}
    for p in outdir.glob('*.csv'):
        m=re.match(r'(.+__P\d{3}R\d{2}V[CAF])_0(_detail)?\.csv$',p.name)
        if m and m.group(1) in manifest:
            produced[(m.group(1),bool(m.group(2)))]=p
    if not produced:
        raise RuntimeError('分割PDFを作成しましたが、AIReadの分割結果CSVが1件も見つかりません。run_assort.bat が input_work を使っているか確認してください。')

    # Choose exactly one variant per logical region. Prefer a candidate classified as one of the
    # five target statements; tie-break by the strategy priority set during splitting.
    by_region=defaultdict(list)
    for stem,(orig,page,region,mode,priority) in manifest.items():
        class_csv=produced.get((stem,False)); ids=_read_ids(class_csv) if class_csv else []
        target_ids=[x for x in ids if x in TARGET_FORMIDS]
        by_region[(orig,page,region)].append((0 if target_ids else 1,priority,stem,target_ids,ids,mode))
    def _detail_richness(stem: str) -> int:
        """GTを見ずにdetail CSVの実データ量だけを数える。

        同じformidを返したvariant同士のtie-break専用。分類結果は変えない。
        """
        dp = produced.get((stem, True))
        if not dp or not dp.exists():
            return -1
        try:
            with dp.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f))
            if len(rows) <= 1:
                return 0
            return sum(1 for row in rows[1:] for v in row if str(v).strip())
        except Exception:
            return -1

    selected={}
    for key,cands in by_region.items():
        # まず従来どおり分類対象formid + strategy priorityで基準候補を決める。
        # その基準候補と「同じ正規化formid」を返したvariantが複数ある場合だけ、
        # detailの非空セルが多いものを採用する。GT値は一切見ないため採点への最適化ではなく、
        # 分類5/5を維持したままOCR detailが欠落しにくいvariantを選ぶ。
        cands.sort(key=lambda x:(x[0],x[1])); base=cands[0]
        same_ids=[x for x in cands if x[0] == base[0] and x[4] == base[4]]
        chosen=max(same_ids, key=lambda x: (_detail_richness(x[2]), -x[1])) if same_ids else base
        selected[key]=chosen[2]
        orig,page,region=key
        logging.info('  🔎 P%d 帳票%d 採用variant=%s AIRead formid: %s detail量=%s',
                     page+1,region,chosen[5],chosen[4] or ['なし'],_detail_richness(chosen[2]))

    # Merge only selected variants back to physical pages.
    # OCR detail is also preserved per logical region.  The historical GT detail CSV belongs
    # to one statement, so evaluator must not compare it with concatenated detail from other
    # statements on the same physical page.
    region_detail_dir = outdir / '.logical_region_details'
    if region_detail_dir.exists():
        shutil.rmtree(region_detail_dir)
    region_detail_dir.mkdir(parents=True, exist_ok=True)

    groups=defaultdict(list); logical=defaultdict(lambda:defaultdict(list))
    for (orig,page,region),stem in selected.items():
        ids=_read_ids(produced.get((stem,False))) if produced.get((stem,False)) else []
        cp=produced.get((stem,False)); dp=produced.get((stem,True))
        detail_name = ''
        if dp:
            detail_name = f'{orig}_{page}_R{region:02d}.csv'
            shutil.copy2(dp, region_detail_dir / detail_name)
        for fid in ids:
            if fid:
                item={'region':region,'formid':fid,'variant':manifest[stem][3]}
                if detail_name: item['detail_file']=detail_name
                logical[orig][str(page)].append(item)
        if cp: groups[(orig,page,False)].append((region,cp))
        if dp: groups[(orig,page,True)].append((region,dp))

    for (orig,page,detail),items in groups.items():
        items.sort(key=lambda x:x[0]); dest=outdir/f'{orig}_{page}{"_detail" if detail else ""}.csv'
        if detail:
            header=None; rows=[]
            for _,src in items:
                with src.open(encoding='utf-8-sig',newline='') as f:
                    rr=csv.reader(f); h=next(rr,None)
                    if h is None: continue
                    if header is None or len(h)>len(header): header=h
                    rows.extend(rr)
            if header:
                with dest.open('w',encoding='utf-8-sig',newline='') as f:
                    ww=csv.writer(f); ww.writerow(header)
                    for r in rows: ww.writerow(r+['']*max(0,len(header)-len(r)))
        else:
            ids=[]
            for _,src in items: ids.extend(_read_ids(src))
            with dest.open('w',encoding='utf-8-sig',newline='') as f:
                ww=csv.writer(f); ww.writerow(['page','formid'])
                for x in ids: ww.writerow([page,x])
            logging.info('  🧩 P%d 統合後 AIRead formid: %s',page+1,ids or ['なし'])

    sidecar={orig:{page:sorted(items,key=lambda x:x['region']) for page,items in pages.items()} for orig,pages in logical.items()}
    sidecar_path=outdir/'.logical_region_formids.json'; sidecar_path.write_text(json.dumps(sidecar,ensure_ascii=False,indent=2),encoding='utf-8')
    logging.info('🧩 logical formid sidecar: %s',sidecar_path)

    # Remove every split-variant CSV; leave only physical-page consolidated files.
    for p in list(outdir.glob('*__P???R??V?_0*.csv')):
        try:p.unlink()
        except OSError:pass
