from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select, text, distinct, case, literal_column

from app.core.database import AsyncSessionLocal
from app.models.achievement import Achievement
from app.models.content import Comment, Guide
from app.models.pipeline import PipelineRun

router = APIRouter()


@router.get("/scrape-status")
async def scrape_status():
    """Detailed scrape coverage: how many achievements have raw HTML, comments, etc."""
    async with AsyncSessionLocal() as session:
        total_achievements = (await session.execute(select(func.count(Achievement.id)))).scalar() or 0
        total_comments = (await session.execute(select(func.count(Comment.id)))).scalar() or 0
        total_guides = (await session.execute(select(func.count(Guide.id)))).scalar() or 0

        # Achievements with at least one comment
        achs_with_comments = (await session.execute(
            select(func.count(distinct(Comment.achievement_id)))
        )).scalar() or 0

        # Comment stats
        comment_stats = (await session.execute(
            select(
                func.min(Comment.upvotes),
                func.max(Comment.upvotes),
                func.avg(Comment.upvotes),
            )
        )).one()

        # Scraped vs unscraped achievements
        scraped = (await session.execute(
            select(func.count(Achievement.id)).where(Achievement.last_scraped_at.isnot(None))
        )).scalar() or 0
        unscraped = total_achievements - scraped

        # Processed vs unprocessed comments
        processed = (await session.execute(
            select(func.count(Comment.id)).where(Comment.is_processed == True)
        )).scalar() or 0
        unprocessed = (await session.execute(
            select(func.count(Comment.id)).where(Comment.is_processed == False)
        )).scalar() or 0

        # Contradictory comments
        contradictory = (await session.execute(
            select(func.count(Comment.id)).where(Comment.is_contradictory == True)
        )).scalar() or 0

        # Comments per achievement distribution (top 10)
        comments_per_ach = (await session.execute(
            select(
                Achievement.name,
                Achievement.blizzard_id,
                func.count(Comment.id).label("cnt"),
            )
            .join(Comment, Comment.achievement_id == Achievement.id)
            .group_by(Achievement.id, Achievement.name, Achievement.blizzard_id)
            .order_by(func.count(Comment.id).desc())
            .limit(10)
        )).all()

        # Check raw storage files via DB (pipeline_runs)
        pipeline_runs = (await session.execute(
            select(PipelineRun.id, PipelineRun.started_at, PipelineRun.completed_at,
                   PipelineRun.achievements_processed, PipelineRun.achievements_errored)
            .order_by(PipelineRun.created_at.desc())
            .limit(5)
        )).all()

    return JSONResponse({
        "total_achievements": total_achievements,
        "total_comments": total_comments,
        "total_guides": total_guides,
        "achievements_scraped": scraped,
        "achievements_unscraped": unscraped,
        "achievements_with_comments": achs_with_comments,
        "achievements_without_comments": total_achievements - achs_with_comments,
        "comment_stats": {
            "min_upvotes": comment_stats[0],
            "max_upvotes": comment_stats[1],
            "avg_upvotes": round(float(comment_stats[2] or 0), 1),
            "processed": processed,
            "unprocessed": unprocessed,
            "contradictory": contradictory,
        },
        "top_commented_achievements": [
            {"name": r[0], "blizzard_id": r[1], "comment_count": r[2]}
            for r in comments_per_ach
        ],
        "recent_pipeline_runs": [
            {
                "id": str(r[0]),
                "started_at": r[1].isoformat() if r[1] else None,
                "completed_at": r[2].isoformat() if r[2] else None,
                "achievements_processed": r[3],
                "achievements_errored": r[4],
            }
            for r in pipeline_runs
        ],
    })


@router.get("/stats")
async def get_stats():
    async with AsyncSessionLocal() as session:
        achievements = (await session.execute(select(func.count(Achievement.id)))).scalar() or 0
        guides = (await session.execute(select(func.count(Guide.id)))).scalar() or 0
        comments = (await session.execute(select(func.count(Comment.id)))).scalar() or 0
        pipeline_runs = (await session.execute(select(func.count(PipelineRun.id)))).scalar() or 0

        # Category breakdown
        categories = (
            await session.execute(
                select(Achievement.category, func.count(Achievement.id))
                .group_by(Achievement.category)
                .order_by(func.count(Achievement.id).desc())
                .limit(50)
            )
        ).all()

        # Recent achievements
        recent = (
            await session.execute(
                select(Achievement.blizzard_id, Achievement.name, Achievement.category, Achievement.points)
                .order_by(Achievement.created_at.desc())
                .limit(10)
            )
        ).all()

        # Guide sources
        guide_sources = (
            await session.execute(
                select(Guide.source_type, func.count(Guide.id))
                .group_by(Guide.source_type)
                .order_by(func.count(Guide.id).desc())
            )
        ).all()

    return JSONResponse({
        "counts": {
            "achievements": achievements,
            "guides": guides,
            "comments": comments,
            "pipeline_runs": pipeline_runs,
        },
        "categories": [{"name": c[0] or "Unknown", "count": c[1]} for c in categories],
        "recent_achievements": [
            {"blizzard_id": r[0], "name": r[1], "category": r[2], "points": r[3]}
            for r in recent
        ],
        "guide_sources": [{"source": s[0] or "Unknown", "count": s[1]} for s in guide_sources],
    })


@router.get("/guides")
async def list_guides(page: int = 1, per_page: int = 50, search: str = ""):
    async with AsyncSessionLocal() as session:
        query = (
            select(
                Guide.id,
                Achievement.blizzard_id,
                Achievement.name,
                Guide.source_type,
                Guide.extracted_zone,
                Guide.requires_flying_extracted,
                Guide.requires_group_extracted,
                Guide.min_group_size_extracted,
                Guide.estimated_minutes_extracted,
                Guide.confidence_score,
                Guide.confidence_flags,
                Guide.steps,
                Guide.processed_at,
                Guide.processed_content,
            )
            .join(Achievement, Achievement.id == Guide.achievement_id)
        )
        if search:
            query = query.where(Achievement.name.ilike(f"%{search}%"))
        query = query.order_by(Guide.processed_at.desc().nullslast()).offset((page - 1) * per_page).limit(per_page)

        rows = (await session.execute(query)).all()

        count_query = select(func.count(Guide.id))
        if search:
            count_query = count_query.join(Achievement, Achievement.id == Guide.achievement_id).where(
                Achievement.name.ilike(f"%{search}%")
            )
        total = (await session.execute(count_query)).scalar() or 0

    return JSONResponse({
        "total": total,
        "page": page,
        "per_page": per_page,
        "guides": [
            {
                "id": str(r[0]),
                "blizzard_id": r[1],
                "achievement_name": r[2],
                "source_type": r[3],
                "zone": r[4],
                "requires_flying": r[5],
                "requires_group": r[6],
                "min_group_size": r[7],
                "estimated_minutes": r[8],
                "confidence_score": round(r[9], 3) if r[9] else None,
                "confidence_flags": (r[10] or {}).get("flags", []),
                "steps": r[11] or [],
                "processed_at": r[12].isoformat() if r[12] else None,
                "coordinates": (r[13] or {}).get("coordinates") if isinstance(r[13], dict) else None,
                "instance_entrance_coords": (r[13] or {}).get("instance_entrance_coords") if isinstance(r[13], dict) else None,
                "waypoints": (r[13] or {}).get("waypoints", []) if isinstance(r[13], dict) else [],
            }
            for r in rows
        ],
    })


@router.get("/achievements")
async def list_achievements(page: int = 1, per_page: int = 50, search: str = ""):
    async with AsyncSessionLocal() as session:
        query = select(
            Achievement.blizzard_id, Achievement.name, Achievement.category,
            Achievement.subcategory, Achievement.points, Achievement.expansion,
            Achievement.is_meta, Achievement.created_at,
        )
        if search:
            query = query.where(Achievement.name.ilike(f"%{search}%"))
        query = query.order_by(Achievement.blizzard_id).offset((page - 1) * per_page).limit(per_page)

        rows = (await session.execute(query)).all()

        count_query = select(func.count(Achievement.id))
        if search:
            count_query = count_query.where(Achievement.name.ilike(f"%{search}%"))
        total = (await session.execute(count_query)).scalar() or 0

    return JSONResponse({
        "total": total,
        "page": page,
        "per_page": per_page,
        "achievements": [
            {
                "blizzard_id": r[0], "name": r[1], "category": r[2],
                "subcategory": r[3], "points": r[4], "expansion": r[5],
                "is_meta": r[6], "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ],
    })


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Achiv-Planner Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; padding: 20px; }
  h1 { color: #ffd100; margin-bottom: 20px; font-size: 24px; }
  h2 { color: #ffd100; margin: 20px 0 10px; font-size: 18px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .stat-card { background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px; padding: 16px; text-align: center; }
  .stat-card .number { font-size: 32px; font-weight: bold; color: #ffd100; }
  .stat-card .label { font-size: 13px; color: #888; margin-top: 4px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  table { width: 100%; border-collapse: collapse; background: #1a1d27; border-radius: 8px; overflow: hidden; }
  th { background: #2a2d37; color: #ffd100; padding: 10px 12px; text-align: left; font-size: 12px; text-transform: uppercase; }
  td { padding: 8px 12px; border-top: 1px solid #2a2d37; font-size: 13px; }
  tr:hover td { background: #22252f; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; background: #2a2d37; }
  .search { margin-bottom: 12px; }
  .search input { background: #1a1d27; border: 1px solid #2a2d37; color: #e0e0e0; padding: 8px 12px; border-radius: 6px; width: 300px; font-size: 14px; }
  .search input:focus { outline: none; border-color: #ffd100; }
  .pagination { margin-top: 12px; display: flex; gap: 8px; }
  .pagination button { background: #2a2d37; border: none; color: #e0e0e0; padding: 6px 14px; border-radius: 4px; cursor: pointer; }
  .pagination button:hover { background: #3a3d47; }
  .pagination button:disabled { opacity: 0.3; cursor: default; }
  .refresh { background: #2a2d37; border: 1px solid #3a3d47; color: #ffd100; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .refresh:hover { background: #3a3d47; }
  #status { color: #888; font-size: 12px; margin-left: 12px; }
  .bar { height: 18px; background: #ffd100; border-radius: 3px; min-width: 2px; }
  .bar-row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
  .bar-label { font-size: 12px; width: 140px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar-count { font-size: 12px; color: #888; min-width: 40px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 16px; }
  .tab { background: #1a1d27; border: 1px solid #2a2d37; color: #888; padding: 8px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 14px; }
  .tab.active { background: #2a2d37; color: #ffd100; border-bottom-color: #2a2d37; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .guide-card { background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .guide-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .guide-title { font-size: 16px; font-weight: bold; color: #ffd100; }
  .guide-meta { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; font-size: 13px; }
  .guide-meta span { background: #2a2d37; padding: 2px 8px; border-radius: 4px; }
  .step-list { list-style: none; padding: 0; }
  .step-item { display: flex; gap: 10px; padding: 8px 0; border-top: 1px solid #2a2d37; font-size: 13px; }
  .step-num { background: #ffd100; color: #0f1117; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px; flex-shrink: 0; }
  .step-type { background: #2a2d37; padding: 1px 6px; border-radius: 3px; font-size: 11px; color: #aaa; }
  .confidence { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
  .confidence.high { background: #1a3a1a; color: #4caf50; }
  .confidence.medium { background: #3a3a1a; color: #ffc107; }
  .confidence.low { background: #3a1a1a; color: #f44336; }
  .flag-list { margin-top: 8px; }
  .flag-item { font-size: 11px; color: #888; padding: 2px 0; }
</style>
</head>
<body>
<h1>Achiv-Planner Dashboard <button class="refresh" onclick="loadAll()">Refresh</button> <span id="status"></span></h1>

<div class="stats" id="stats"></div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('overview')">Overview</div>
  <div class="tab" onclick="switchTab('guides')">Guides</div>
  <div class="tab" onclick="switchTab('achievements')">Achievements</div>
</div>

<div id="tab-overview" class="tab-content active">
  <div class="grid">
    <div>
      <h2>Categories</h2>
      <div id="categories"></div>
    </div>
    <div>
      <h2>Guide Sources</h2>
      <div id="sources"></div>
      <h2>Recent Achievements</h2>
      <table><thead><tr><th>ID</th><th>Name</th><th>Category</th><th>Pts</th></tr></thead><tbody id="recent"></tbody></table>
    </div>
  </div>
</div>

<div id="tab-guides" class="tab-content">
  <div class="search"><input id="guideSearchInput" placeholder="Search guides by achievement name..." oninput="guideSearchDebounced()"></div>
  <div id="guideList"></div>
  <div class="pagination">
    <button id="guidePrevBtn" onclick="changeGuidePage(-1)">Prev</button>
    <span id="guidePageInfo" style="padding:6px;font-size:13px;color:#888"></span>
    <button id="guideNextBtn" onclick="changeGuidePage(1)">Next</button>
  </div>
</div>

<div id="tab-achievements" class="tab-content">
  <div class="search"><input id="searchInput" placeholder="Search achievements..." oninput="searchDebounced()"></div>
  <table><thead><tr><th>Blizzard ID</th><th>Name</th><th>Category</th><th>Sub</th><th>Pts</th><th>Expansion</th><th>Meta</th></tr></thead><tbody id="achList"></tbody></table>
  <div class="pagination">
    <button id="prevBtn" onclick="changePage(-1)">Prev</button>
    <span id="pageInfo" style="padding:6px;font-size:13px;color:#888"></span>
    <button id="nextBtn" onclick="changePage(1)">Next</button>
  </div>
</div>

<script>
let currentPage = 1, totalAch = 0, searchTimer;
let guidePage = 1, totalGuides = 0, guideSearchTimer;
const API = window.location.origin + '/api/dashboard';

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelector(`.tab-content#tab-${name}`).classList.add('active');
  event.target.classList.add('active');
  if (name === 'guides') loadGuides();
  if (name === 'achievements') loadAchievements();
}

function confidenceClass(score) {
  if (score >= 0.65) return 'high';
  if (score >= 0.4) return 'medium';
  return 'low';
}

function fmtCoord(c) {
  if (!c || c.x == null) return '';
  return `${c.x.toFixed(1)}, ${c.y.toFixed(1)}` + (c.zone ? ` (${c.zone})` : '');
}

function renderGuide(g) {
  const steps = (g.steps || []).map(s =>
    `<li class="step-item">
      <span class="step-num">${s.order || '?'}</span>
      <div>
        <span>${s.description || ''}</span>
        ${s.location ? ` <span class="step-type">${s.location}</span>` : ''}
        ${s.step_type ? ` <span class="step-type">${s.step_type}</span>` : ''}
        ${s.coordinates ? ` <span class="step-type" style="color:#4fc3f7">/way ${s.coordinates.zone || g.zone || ''} ${s.coordinates.x} ${s.coordinates.y}</span>` : ''}
      </div>
    </li>`
  ).join('');

  const waypoints = (g.waypoints || []).map(w =>
    `<code style="display:block;font-size:12px;color:#4fc3f7;padding:2px 0">/way ${w.zone || ''} ${w.x} ${w.y} ${w.label || ''}</code>`
  ).join('');

  const flags = (g.confidence_flags || []).map(f =>
    `<div class="flag-item">- ${f}</div>`
  ).join('');

  const coords = g.coordinates ? fmtCoord(g.coordinates) : '';
  const entrance = g.instance_entrance_coords ? fmtCoord(g.instance_entrance_coords) : '';

  return `<div class="guide-card">
    <div class="guide-header">
      <span class="guide-title">${g.achievement_name} <span style="color:#888;font-weight:normal;font-size:13px">#${g.blizzard_id}</span></span>
      <span class="confidence ${confidenceClass(g.confidence_score || 0)}">${g.confidence_score ? (g.confidence_score * 100).toFixed(0) + '%' : 'N/A'}</span>
    </div>
    <div class="guide-meta">
      ${g.zone ? `<span>Zone: ${g.zone}</span>` : ''}
      ${coords ? `<span style="color:#4fc3f7">Coords: ${coords}</span>` : ''}
      ${entrance ? `<span style="color:#4fc3f7">Entrance: ${entrance}</span>` : ''}
      ${g.estimated_minutes ? `<span>~${g.estimated_minutes} min</span>` : ''}
      ${g.requires_group ? `<span>Group${g.min_group_size ? ': ' + g.min_group_size + '+' : ''}</span>` : '<span>Solo</span>'}
      ${g.requires_flying ? '<span>Flying req.</span>' : ''}
      <span>${g.source_type || 'unknown'}</span>
    </div>
    ${steps ? `<ul class="step-list">${steps}</ul>` : '<p style="color:#666;font-size:13px">No steps extracted</p>'}
    ${waypoints ? `<div style="margin-top:8px;background:#1a2a3a;padding:8px;border-radius:4px"><strong style="font-size:11px;color:#4fc3f7">TomTom Waypoints:</strong>${waypoints}</div>` : ''}
    ${flags ? `<div class="flag-list"><strong style="font-size:11px;color:#666">Confidence flags:</strong>${flags}</div>` : ''}
  </div>`;
}

async function loadGuides() {
  const search = document.getElementById('guideSearchInput').value;
  const r = await fetch(API + '/guides?page=' + guidePage + '&per_page=20&search=' + encodeURIComponent(search));
  const d = await r.json();
  totalGuides = d.total;
  document.getElementById('guideList').innerHTML = d.guides.length
    ? d.guides.map(renderGuide).join('')
    : '<p style="color:#666;padding:20px;text-align:center">No guides yet — run LLM enrichment first</p>';
  const totalPages = Math.ceil(totalGuides / 20);
  document.getElementById('guidePageInfo').textContent = 'Page ' + guidePage + ' of ' + totalPages + ' (' + totalGuides + ' guides)';
  document.getElementById('guidePrevBtn').disabled = guidePage <= 1;
  document.getElementById('guideNextBtn').disabled = guidePage >= totalPages;
}

function changeGuidePage(d) { guidePage += d; loadGuides(); }
function guideSearchDebounced() { clearTimeout(guideSearchTimer); guideSearchTimer = setTimeout(() => { guidePage = 1; loadGuides(); }, 300); }

async function loadStats() {
  try {
    document.getElementById('status').textContent = 'Loading...';
    const r = await fetch(API + '/stats');
    const d = await r.json();
    const c = d.counts;
    document.getElementById('stats').innerHTML =
      card(c.achievements, 'Achievements') + card(c.guides, 'Guides') +
      card(c.comments, 'Comments') + card(c.pipeline_runs, 'Pipeline Runs');

    const maxCat = Math.max(...d.categories.map(x => x.count), 1);
    document.getElementById('categories').innerHTML = d.categories.map(x =>
      `<div class="bar-row"><span class="bar-label">${x.name}</span><div class="bar" style="width:${x.count/maxCat*200}px"></div><span class="bar-count">${x.count}</span></div>`
    ).join('');

    const maxSrc = Math.max(...d.guide_sources.map(x => x.count), 1);
    document.getElementById('sources').innerHTML = d.guide_sources.length ?
      d.guide_sources.map(x =>
        `<div class="bar-row"><span class="bar-label">${x.source}</span><div class="bar" style="width:${x.count/maxSrc*200}px"></div><span class="bar-count">${x.count}</span></div>`
      ).join('') : '<p style="color:#666;font-size:13px">No guides yet</p>';

    document.getElementById('recent').innerHTML = d.recent_achievements.map(a =>
      `<tr><td>${a.blizzard_id}</td><td>${a.name}</td><td><span class="badge">${a.category||'-'}</span></td><td>${a.points}</td></tr>`
    ).join('');
    document.getElementById('status').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) { document.getElementById('status').textContent = 'Error: ' + e.message; }
}

async function loadAchievements() {
  const search = document.getElementById('searchInput').value;
  const r = await fetch(API + `/achievements?page=${currentPage}&per_page=50&search=${encodeURIComponent(search)}`);
  const d = await r.json();
  totalAch = d.total;
  document.getElementById('achList').innerHTML = d.achievements.map(a =>
    `<tr><td>${a.blizzard_id}</td><td>${a.name}</td><td><span class="badge">${a.category||'-'}</span></td><td>${a.subcategory||'-'}</td><td>${a.points}</td><td>${a.expansion||'-'}</td><td>${a.is_meta?'Yes':''}</td></tr>`
  ).join('') || '<tr><td colspan="7" style="text-align:center;color:#666;padding:20px">No achievements yet — pipeline is still running</td></tr>';
  const totalPages = Math.ceil(totalAch / 50);
  document.getElementById('pageInfo').textContent = `Page ${currentPage} of ${totalPages} (${totalAch} total)`;
  document.getElementById('prevBtn').disabled = currentPage <= 1;
  document.getElementById('nextBtn').disabled = currentPage >= totalPages;
}

function card(n, label) { return `<div class="stat-card"><div class="number">${n.toLocaleString()}</div><div class="label">${label}</div></div>`; }
function changePage(d) { currentPage += d; loadAchievements(); }
function searchDebounced() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { currentPage = 1; loadAchievements(); }, 300); }
function loadAll() { loadStats(); loadAchievements(); }
loadAll();
setInterval(loadStats, 30000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    return HTMLResponse(DASHBOARD_HTML)
