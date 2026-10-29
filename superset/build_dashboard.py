# Builds the Churn House dashboard via the Superset API - no clicking.
# Run:  uv run python superset/build_dashboard.py
# Idempotent: existing charts / dashboard are re-used by name.
# Gate checks compare every chart against live trino before saving.
import json

from trino.dbapi import connect

from seed_superset import SCHEMA, call, fail, list_datasets, login_as

TITLE = "Churn House"
HERO_MD = (
    "# CHURN HOUSE\n\n"
    "### high-risk customers churn **6.7×** more than safe ones — "
    "5 SQL rules decide who is next"
)
HERO_CSS = (
    ".dashboard .dashboard-markdown { text-align: center; padding-top: 8px; } "
    ".dashboard .dashboard-markdown h1 { font-size: 44px; font-weight: 800; "
    "letter-spacing: 6px; margin: 0 0 6px 0; } "
    ".dashboard .dashboard-markdown h3 { font-weight: 400; margin: 0; "
    "font-size: 18px; color: #58595b; } "
    ".dashboard .dashboard-markdown strong { font-weight: 700; }"
)


def truth():
    """The numbers the charts MUST show, read straight from trino gold."""
    c = connect(host="localhost", port=8080, user="admin", catalog="iceberg", schema="gold")
    cur = c.cursor()
    cur.execute("select revenue from monthly_revenue order by month_start")
    revenue = [r[0] for r in cur.fetchall()]
    cur.execute("""select band, customers, churn_pct from risk_validation
                   order by case band when 'low' then 1 when 'medium' then 2 else 3 end""")
    bands = [(b, int(cust), float(pct)) for b, cust, pct in cur.fetchall()]
    cur.execute("select count(*) from customer_risk where band = 'high' and not churn")
    active_high = cur.fetchone()[0]
    return revenue, bands, active_high


def find_dataset(datasets, table):
    for d in datasets:
        if d["table_name"] == table and d["schema"] == SCHEMA:
            return d
    fail(f"dataset {table} not registered (run seed_superset.py first)")


def hydrate(dataset, token, csrf):
    """The list endpoint ships without columns; the detail endpoint has them."""
    code, out = call("GET", f"/api/v1/dataset/{dataset['id']}", token=token, csrf=csrf)
    if code != 200:
        fail(f"dataset detail {dataset['table_name']} returned {code}: {out}")
    return out["result"]


def column(dataset, name):
    for c in dataset.get("columns") or []:
        if c["column_name"] == name:
            return c
    fail(f"column {name} missing on {dataset['table_name']}")


def simple_metric(dataset, name, agg):
    return {"expressionType": "SIMPLE", "aggregate": agg,
            "column": column(dataset, name), "label": name}


def qc(dataset, groupby, metrics, filters=None, granularity=None,
       time_grain=None, row_limit=1000, orderby=None):
    """Build the query-context object POST /api/v1/chart/data wants."""
    q = {"groupby": groupby, "metrics": metrics, "filters": filters or [],
         "row_limit": row_limit, "row_offset": 0, "orderby": orderby or [],
         "series_limit": None, "series_limit_metric": None,
         "series_columns": None, "timeseries_limit": None,
         "timeseries_limit_metric": None, "order_desc": True,
         "sort_by_metric": False}
    if granularity:
        q["granularity"] = granularity
        q["time_grain"] = time_grain
        q["time_range"] = ""
    return {"datasource": {"id": dataset["id"], "type": "table"},
            "queries": [q], "form_data": {},
            "result_format": "json", "result_type": "full"}


def run_query(qc_obj, token, csrf):
    """Dry-run a query context and return rows as dicts."""
    code, out = call("POST", "/api/v1/chart/data", qc_obj, token=token, csrf=csrf)
    if code != 200:
        fail(f"chart query failed {code}: {str(out)[:500]}")
    res = out["result"][0]
    if res.get("status") != "success":
        fail(f"chart query error: {str(res)[:500]}")
    rows = res.get("data") or []
    if rows and not isinstance(rows[0], dict):
        cols = res.get("colnames") or []
        rows = [dict(zip(cols, row)) for row in rows]
    return rows


def render_check(chart_id, token, csrf):
    """How the SAVED chart actually renders (params fully applied)."""
    code, out = call("GET", f"/api/v1/chart/{chart_id}/data/", {}, token=token, csrf=csrf)
    if code != 200:
        fail(f"render check of chart {chart_id} failed {code}: {str(out)[:500]}")
    res = out["result"][0]
    if res.get("status") != "success":
        fail(f"render error of chart {chart_id}: {str(res)[:500]}")
    rows = res.get("data") or []
    if rows and not isinstance(rows[0], dict):
        cols = res.get("colnames") or []
        rows = [dict(zip(cols, row)) for row in rows]
    return rows


def existing_charts(token, csrf):
    code, out = call("GET", "/api/v1/chart/?page_size=100", token=token, csrf=csrf)
    if code != 200:
        fail(f"list charts returned {code}: {out}")
    return {c["slice_name"]: c["id"] for c in out["result"]}


def save_chart(name, viz_type, params_obj, ds, qc_obj, dash_id, token, csrf):
    params = dict(params_obj)
    params["datasource"] = f"{ds['id']}__table"
    charts = existing_charts(token, csrf)
    if name in charts:
        print(f"  (chart already exists: {name}, id {charts[name]} - refreshing it)")
        chart_id = charts[name]
        # keep the saved chart in sync with the script (viz_type + params)
        code, out = call("PUT", f"/api/v1/chart/{chart_id}",
                         {"viz_type": viz_type, "params": json.dumps(params)},
                         token=token, csrf=csrf)
        if code != 200:
            fail(f"chart {name} refresh failed {code}: {str(out)[:500]}")
    else:
        code, out = call("POST", "/api/v1/chart/",
                         {"slice_name": name, "datasource_id": ds["id"],
                          "datasource_type": "table", "viz_type": viz_type,
                          "params": json.dumps(params)},
                         token=token, csrf=csrf)
        if code != 201:
            fail(f"chart {name} save failed {code}: {str(out)[:500]}")
        chart_id = out["id"]
        print(f"  saved chart: {name} (id {chart_id})")
    # the chart data endpoint reads the SAVED query context - write it explicitly
    code, out = call("PUT", f"/api/v1/chart/{chart_id}",
                     {"query_context": json.dumps(qc_obj)}, token=token, csrf=csrf)
    if code != 200:
        fail(f"chart {name} query_context save failed {code}: {str(out)[:500]}")
    # bind the chart to the dashboard (the api layer does not do it from the layout)
    code, out = call("PUT", f"/api/v1/chart/{chart_id}",
                     {"dashboards": [dash_id]}, token=token, csrf=csrf)
    if code != 200:
        fail(f"chart {name} dashboard binding failed {code}: {str(out)[:500]}")
    return chart_id


def get_or_create_dashboard(token, csrf):
    code, out = call("GET", "/api/v1/dashboard/?page_size=100", token=token, csrf=csrf)
    if code != 200:
        fail(f"list dashboards returned {code}: {out}")
    for d in out["result"]:
        if d["dashboard_title"] != TITLE:
            continue
        code, det = call("GET", f"/api/v1/dashboard/{d['id']}", token=token, csrf=csrf)
        pos = json.loads(det["result"].get("position_json") or "{}")
        try:
            validate_positions(pos)
            healthy = "ROOT_ID" in pos
        except (AssertionError, KeyError, TypeError):
            healthy = False
        if not healthy:
            print(f"  (dashboard {d['id']} has a broken layout - rebuilding)")
            code, _ = call("DELETE", f"/api/v1/dashboard/{d['id']}",
                           token=token, csrf=csrf)
            if code != 200:
                fail(f"delete of broken dashboard returned {code}")
            break
        print(f"  (dashboard already exists: {TITLE}, id {d['id']})")
        return d["id"]
    code, out = call("POST", "/api/v1/dashboard/",
                     {"dashboard_title": TITLE}, token=token, csrf=csrf)
    if code != 201:
        fail(f"dashboard create returned {code}: {str(out)[:500]}")
    print(f"  dashboard created: {TITLE} (id {out['id']})")
    return out["id"]


def layout_positions(chart_ids):
    hero, a, b, c, d = "MD-1", "CH-A", "CH-B", "CH-C", "CH-D"
    bg = {"background": "BACKGROUND_TRANSPARENT"}
    return {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": TITLE}},
        "GRID_ID": {"id": "GRID_ID", "type": "GRID", "meta": bg,
                    "children": ["ROW-0", "ROW-1", "ROW-2", "ROW-3"]},
        "ROW-0": {"id": "ROW-0", "type": "ROW", "children": [hero], "meta": bg},
        hero: {"id": hero, "type": "MARKDOWN", "children": [],
               "meta": {"text": HERO_MD, "headerSize": "small",
                        "width": 12, "height": 10}},
        "ROW-1": {"id": "ROW-1", "type": "ROW", "children": [a, b], "meta": bg},
        a: {"id": a, "type": "CHART", "children": [],
            "meta": {"chartId": chart_ids["a"], "width": 8, "height": 60}},
        b: {"id": b, "type": "CHART", "children": [],
            "meta": {"chartId": chart_ids["b"], "width": 4, "height": 60}},
        "ROW-2": {"id": "ROW-2", "type": "ROW", "children": [c], "meta": bg},
        c: {"id": c, "type": "CHART", "children": [],
            "meta": {"chartId": chart_ids["c"], "width": 12, "height": 50}},
        "ROW-3": {"id": "ROW-3", "type": "ROW", "children": [d], "meta": bg},
        d: {"id": d, "type": "CHART", "children": [],
            "meta": {"chartId": chart_ids["d"], "width": 12, "height": 70}},
    }


def validate_positions(pos):
    """Mirror what the frontend loads: every usable node needs meta + sizing."""
    assert pos.get("DASHBOARD_VERSION_KEY") == "v2", "wrong version marker"
    assert "ROOT_ID" in pos and "GRID_ID" in pos, "tree root missing"
    for row_id in pos["GRID_ID"]["children"]:
        row = pos[row_id]
        assert row["type"] == "ROW", "grid children must be ROWs"
        assert isinstance(row.get("meta"), dict), f"{row_id} row missing meta"
        for cell_id in row["children"]:
            meta = pos[cell_id].get("meta")
            assert isinstance(meta, dict), f"{cell_id} missing meta"
            assert "width" in meta and "height" in meta, \
                f"{cell_id} meta missing width/height"
    return True


def save_layout(dash_id, chart_ids, token, csrf):
    positions = layout_positions(chart_ids)
    validate_positions(positions)
    code, out = call("PUT", f"/api/v1/dashboard/{dash_id}",
                     {"position_json": json.dumps(positions),
                      "json_metadata": json.dumps({"label_colors": {
                          "low": "#59A14F", "medium": "#F28E2B", "high": "#E15759"}}),
                      "css": HERO_CSS,
                      "published": True},
                     token=token, csrf=csrf)
    if code != 200:
        fail(f"dashboard layout save returned {code}: {str(out)[:500]}")
    print("  layout saved + dashboard published ✓")


def main():
    revenue_truth, band_truth, active_high = truth()
    months = len(revenue_truth)
    rev_total = round(sum(revenue_truth), 2)
    churn_truth = {b: v for b, _, v in band_truth}
    cust_truth = {b: c for b, c, _ in band_truth}
    print(f"truth from trino: {months} months, ${rev_total} revenue, "
          f"{active_high} active high-risk")

    token, csrf = login_as()
    datasets = list_datasets(token, csrf)
    ds_rev = hydrate(find_dataset(datasets, "monthly_revenue"), token, csrf)
    ds_val = hydrate(find_dataset(datasets, "risk_validation"), token, csrf)
    ds_risk = hydrate(find_dataset(datasets, "customer_risk"), token, csrf)

    # ---- chart A: revenue line (gate: months + revenue total) -----------------
    qc_line = qc(ds_rev, ["month_start"], [simple_metric(ds_rev, "revenue", "SUM")],
                 granularity="month_start", time_grain="P1M")
    rows = run_query(qc_line, token, csrf)
    revs = [r.get("revenue") for r in rows]
    ok = len(rows) == months and abs(round(sum(revs), 2) - rev_total) < 0.01
    print("  gate A (revenue line):", "PASS"
          if ok else f"FAIL rows={len(rows)} sum={round(sum(revs) or 0, 2)}")
    if not ok:
        fail("chart A gate failed - not saving")
    line_params = {"viz_type": "echarts_timeseries_line",
                   "datasetId": ds_rev["id"],
                   "x_axis": "month_start", "time_grain_sqla": "P1M",
                   "x_axis_format": "%b %Y", "seriesType": "start",
                   "metrics": [simple_metric(ds_rev, "revenue", "SUM")],
                   "y_axis_label": "revenue $", "y_axis_format": "SMART_NUMBER",
                   "color_scheme": "supersetColors"}

    # ---- chart B: customers donut (gate: 4919/1578/546) ----------------------
    qc_pie = qc(ds_val, ["band"], [simple_metric(ds_val, "customers", "SUM")],
                orderby=[["customers", False]])
    rows = run_query(qc_pie, token, csrf)
    by_band = {r.get("band"): r.get("customers") for r in rows}
    ok = by_band == cust_truth
    print("  gate B (donut):", "PASS" if ok else f"FAIL {by_band}")
    if not ok:
        fail("chart B gate failed - not saving")
    # ---- chart B: customers by band as BARS (gate: 4919/1578/546) -------------
    # the pie plugin's param contract proved brittle from the api; the bar
    # plugin contract is proven by chart C (same form, renders fine). same
    # story, a shape that will not crash the frontend. permanent call.
    custbar_params = {"viz_type": "echarts_timeseries_bar",
                      "datasetId": ds_val["id"],
                      "x_axis": "band",
                      "metrics": [simple_metric(ds_val, "customers", "SUM")],
                      "sort_by_metric": True,
                      "show_value": True,
                      "y_axis_format": "SMART_NUMBER",
                      "color_scheme": "supersetColors"}

    # ---- chart C: churn % staircase (gate: 12.3/51.3/83.0) -------------------
    mob = simple_metric(ds_val, "churn_pct", "AVG")
    qc_bar = qc(ds_val, ["band"], [mob], orderby=[["churn_pct", False]])
    rows = run_query(qc_bar, token, csrf)
    vals_found = sorted({round(r.get("churn_pct"), 1) for r in rows})
    ok = vals_found == sorted(round(v, 1) for v in churn_truth.values())
    print("  gate C (values):", "PASS" if ok else f"FAIL {vals_found}")
    if not ok:
        fail("chart C gate failed - not saving")
    bar_params = {"viz_type": "echarts_timeseries_bar",
                  "datasetId": ds_val["id"],
                  "x_axis": "band",
                  "metrics": [mob],
                  "sort_by_metric": True,
                  "show_value": True, "y_axis_format": "SMART_NUMBER",
                  "color_scheme": "supersetColors"}

    # ---- chart D: top-20 call list (gate: 20 high-band active rows) ----------
    table_qc = qc(ds_risk,
                  ["customer_id", "band", "score", "churn", "contract",
                   "tenure", "failed_last_90d", "reasons"],
                  [{"expressionType": "SQL", "sqlExpression": "count(*)",
                    "label": "COUNT(*)"}],
                  filters=[{"col": "band", "op": "==", "val": "high"},
                           {"col": "churn", "op": "==", "val": False}],
                  row_limit=20,
                  orderby=[["score", False]])
    rows = run_query(table_qc, token, csrf)
    ok = len(rows) == 20 and all(r.get("band") == "high" and not r.get("churn")
                                 for r in rows)
    scores = [r.get("score") for r in rows]
    print(f"  gate D (call list, scores {scores[:5]}...):",
          "PASS" if ok else "FAIL")
    if not ok:
        fail("chart D gate failed - not saving")
    table_params = {"viz_type": "table",
                    "datasetId": ds_risk["id"],
                    "columns": ["customer_id", "band", "score", "churn",
                                "contract", "tenure", "failed_last_90d", "reasons"],
                    "metrics": [{"expressionType": "SQL", "sqlExpression": "count(*)",
                                 "label": "COUNT(*)"}],
                    "adhoc_filters": [
                        {"clause": "WHERE", "expressionType": "SQL",
                         "sqlExpression": "band = 'high'"},
                        {"clause": "WHERE", "expressionType": "SQL",
                         "sqlExpression": "not churn"}],
                    "row_limit": 20}

    # ---- save + verify rendered output ----------------------------------------
    print("\nsaving:")
    dash_id = get_or_create_dashboard(token, csrf)
    chart_ids = {
        "a": save_chart("Revenue by month", "echarts_timeseries_line",
                        line_params, ds_rev, qc_line, dash_id, token, csrf),
        "b": save_chart("Customers by band", "echarts_timeseries_bar",
                        custbar_params, ds_val, qc_pie, dash_id, token, csrf),
        "c": save_chart("Churn % by band", "echarts_timeseries_bar",
                        bar_params, ds_val, qc_bar, dash_id, token, csrf),
        "d": save_chart("Top 20 at risk (still active)", "table",
                        table_params, ds_risk, table_qc, dash_id, token, csrf),
    }

    # both bar charts must render ordered by their metric, biggest first
    # (sort_by_metric draws it; the desc orderby keeps the data in that order)
    rows = render_check(chart_ids["b"], token, csrf)
    counts = [int(r.get("customers")) for r in rows]
    order = [r.get("band") for r in rows]
    ok = len(rows) == 3 and counts == sorted(counts, reverse=True)
    print("  chart B rendered order:", list(zip(order, counts)),
          "PASS" if ok else "FAIL")
    if not ok:
        fail("chart B renders out of metric order - not saving layout")

    rows = render_check(chart_ids["c"], token, csrf)
    pcts = [round(float(r.get("churn_pct")), 1) for r in rows]
    order = [r.get("band") for r in rows]
    ok = len(rows) == 3 and pcts == sorted(pcts, reverse=True)
    print("  chart C rendered order:", list(zip(order, pcts)),
          "PASS" if ok else "FAIL")
    if not ok:
        fail("chart C renders out of metric order - not saving layout")

    ok_d = render_check(chart_ids["d"], token, csrf)
    print(f"  chart D rendered rows: {len(ok_d)}")

    save_layout(dash_id, chart_ids, token, csrf)
    print(f"\ndashboard ready: http://localhost:8088/superset/dashboard/{dash_id}")
    print("left for the human: open it, look at it, screenshot it -> docs/img/")


if __name__ == "__main__":
    main()
