async def scrape_standings(page, league: dict) -> None:
    standings_url = league.get("standings_url")
    if not standings_url:
        print(f"   ⏭️  No standings for {league['name']}")
        return

    doc_name = league["key"]
    league_logo = league.get("league_logo", "")
    print(f"   ⏳ Standings → {league['name']} ...")

    await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_standings.png")
    with open(f"debug/{doc_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    # Get all rank-rows
    rows = await page.query_selector_all("div.rank-row:not(.header)")
    
    table: List[Dict] = []
    max_teams = 30  # Safety limit (most leagues have <30 teams)
    
    for row in rows:
        try:
            # Check if we've hit the player standings section
            header_check = await row.query_selector("div.rank-col.name")
            if header_check:
                header_text = (await header_check.inner_text()).strip().lower()
                # Stop if we hit "Players" section
                if header_text == "players" or "player" in header_text:
                    break
            
            # Position must be a digit
            pos_el = await row.query_selector("div.rank-col.number")
            position = (await pos_el.inner_text()).strip() if pos_el else ""
            if not position or not position.isdigit():
                continue

            # Team name
            name_div = await row.query_selector("div.rank-col.name div.team-name")
            team = ""
            team_logo = ""
            if name_div:
                img = await name_div.query_selector("img")
                if img:
                    team_logo = (await img.get_attribute("src") or "").strip()
                info_div = await name_div.query_selector("div.info")
                team = (await info_div.inner_text()).strip() if info_div else ""
            else:
                name_div = await row.query_selector("div.rank-col.name")
                team = (await name_div.inner_text()).strip() if name_div else ""

            if not team:
                continue

            # Stats
            played_el = await row.query_selector("div.rank-col.played")
            win_el = await row.query_selector("div.rank-col.win")
            equal_el = await row.query_selector("div.rank-col.equal")
            lose_el = await row.query_selector("div.rank-col.lose")
            goals_el = await row.query_selector("div.rank-col.goals")
            diff_el = await row.query_selector("div.rank-col.diff")
            points_el = await row.query_selector("div.rank-col.points")

            played = (await played_el.inner_text()).strip() if played_el else ""
            wins = (await win_el.inner_text()).strip() if win_el else ""
            draws = (await equal_el.inner_text()).strip() if equal_el else ""
            losses = (await lose_el.inner_text()).strip() if lose_el else ""
            goals = (await goals_el.inner_text()).strip() if goals_el else ""
            diff = (await diff_el.inner_text()).strip() if diff_el else ""
            points = (await points_el.inner_text()).strip() if points_el else ""

            table.append({
                "position":  position,
                "team":      team,
                "team_logo": team_logo,
                "played":    played,
                "wins":      wins,
                "draws":     draws,
                "losses":    losses,
                "goals":     goals,
                "diff":      diff,
                "points":    points,
            })
            
            # Safety: stop if we reach max teams
            if len(table) >= max_teams:
                break

        except Exception as e:
            print(f"      ⚠️ Skipped row: {e}")
            continue

    doc_id = f"flashscore_{doc_name}_standings"
    if table:
        save(doc_id, {
            "league_name": league["name"],
            "league_logo": league_logo,
            "table":     table,
            "count":     len(table),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(table):>3} rows STANDINGS → {doc_id}")
    else:
        print(f"   ⚠️  No standings rows")
