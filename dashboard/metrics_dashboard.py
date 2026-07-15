#!/usr/bin/env python3
"""COMET-RIOBAMBA v4.1 - Metrics Dashboard"""
import argparse, re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import plotly.graph_objects as go
import dash
from dash import dcc, html, Input, Output
import pandas as pd

DEFAULT_LOG_PATH = Path("logs/agent.log")
DEFAULT_PORT = 8050
REFRESH_INTERVAL = 30
HISTORY_WINDOW = 24

class LogParser:
    PATTERNS = {
        "cycle_end": r"CICLO #\d+ FINALIZADO in ([\d.]+)s",
        "post_published": r"Moltbook create_post OK: status=(\d+)",
        "vibration": r"Vibración: ([\d.]+)",
        "waiting_next": r"Esperando (\d+)s hasta",
    }
    def __init__(self, log_path):
        self.log_path = log_path
        self.metrics = {"cycles": deque(maxlen=100), "publishes": deque(maxlen=100), 
                       "vibrations": deque(maxlen=100), "errors": deque(maxlen=50), "last_update": None}
    
    def parse_line(self, line):
        result = {}
        for key, pattern in self.PATTERNS.items():
            m = re.search(pattern, line)
            if m: result[key] = m.group(1) if m.groups() else True; break
        ts = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if ts: result["timestamp"] = datetime.strptime(ts.group(1), "%Y-%m-%d %H:%M:%S")
        if "ERROR" in line: result["level"], result["message"] = "ERROR", line.strip()
        return result if result else None
    
    def parse_recent(self, lines=500):
        if not self.log_path.exists(): return self.metrics
        with open(self.log_path, "r", encoding="utf-8") as f:
            recent = f.readlines()[-lines:]
        for line in recent:
            p = self.parse_line(line)
            if not p: continue
            if "cycle_end" in p: self.metrics["cycles"].append({"duration": float(p["cycle_end"]), "ts": p.get("timestamp")})
            if "post_published" in p: self.metrics["publishes"].append({"status": int(p["post_published"]), "ts": p.get("timestamp")})
            if "vibration" in p: self.metrics["vibrations"].append({"value": float(p["vibration"]), "ts": p.get("timestamp")})
            if p.get("level") == "ERROR": self.metrics["errors"].append({"msg": p.get("message","")[:150], "ts": p.get("timestamp")})
        self.metrics["last_update"] = datetime.now()
        return self.metrics
    
    def get_summary(self):
        m = self.metrics; now = datetime.now(); cutoff = now - timedelta(hours=HISTORY_WINDOW)
        cycles = [c for c in m["cycles"] if c.get("ts") and c["ts"] > cutoff]
        pubs = [p for p in m["publishes"] if p.get("ts") and p["ts"] > cutoff]
        errs = [e for e in m["errors"] if e.get("ts") and e["ts"] > cutoff]
        avg_dur = sum(c["duration"] for c in cycles)/len(cycles) if cycles else 0
        pub_rate = len([p for p in pubs if p["status"]==201])/len(pubs)*100 if pubs else 100
        next_est = None
        if cycles and cycles[-1].get("ts"):
            interval = 14400  # default 4h
            with open(self.log_path, "r", encoding="utf-8") as f:
                for ln in reversed(f.readlines()[-50:]):
                    wm = re.search(r"Esperando (\d+)s", ln)
                    if wm: interval = int(wm.group(1)); break
            next_est = (cycles[-1]["ts"] + timedelta(seconds=interval)).strftime("%Y-%m-%d %H:%M")
        return {"cycles": len(cycles), "avg_duration": avg_dur, "publish_rate": pub_rate, 
                "errors": len(errs), "next_cycle": next_est, "last_update": m["last_update"]}

def create_app(parser):
    app = dash.Dash(__name__, update_title=None); app.title = "COMET-RIOBAMBA Metrics"
    app.layout = html.Div([
        html.H1("🚀 COMET-RIOBAMBA v4.1 - Metrics", style={"textAlign":"center","color":"#2c3e50","margin":"20px"}),
        html.Div(id="last-update", style={"textAlign":"center","color":"#7f8c8d","marginBottom":"20px"}),
        html.Div([
            html.Div([html.H3(id="kpi-cycles",style={"color":"#3498db"}), html.P("Ciclos (24h)")], 
                    style={"flex":1,"padding":"15px","background":"white","borderRadius":"8px","margin":"10px","textAlign":"center"}),
            html.Div([html.H3(id="kpi-publish",style={"color":"#2ecc71"}), html.P("Éxito publicación")], 
                    style={"flex":1,"padding":"15px","background":"white","borderRadius":"8px","margin":"10px","textAlign":"center"}),
            html.Div([html.H3(id="kpi-errors",style={"color":"#e74c3c"}), html.P("Errores (24h)")], 
                    style={"flex":1,"padding":"15px","background":"white","borderRadius":"8px","margin":"10px","textAlign":"center"}),
            html.Div([html.H3(id="kpi-next",style={"color":"#9b59b6"}), html.P("Próximo ciclo")], 
                    style={"flex":1,"padding":"15px","background":"white","borderRadius":"8px","margin":"10px","textAlign":"center"}),
        ], style={"display":"flex","flexWrap":"wrap","justifyContent":"center"}),
        html.Div([
            html.Div([html.H4("Duración de Ciclos"), dcc.Graph(id="chart-duration")], style={"flex":1,"minWidth":"400px","padding":"10px"}),
            html.Div([html.H4("Tasa de Publicación"), dcc.Graph(id="chart-publish")], style={"flex":1,"minWidth":"400px","padding":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap"}),
        html.Div([
            html.Div([html.H4("Vibración"), dcc.Graph(id="chart-vibration")], style={"flex":1,"minWidth":"400px","padding":"10px"}),
            html.Div([html.H4("Errores Recientes"), html.Div(id="error-list", style={"maxHeight":"250px","overflowY":"auto","fontSize":"12px","fontFamily":"monospace"})], style={"flex":1,"minWidth":"400px","padding":"10px"}),
        ], style={"display":"flex","flexWrap":"wrap"}),
        dcc.Interval(id="interval", interval=REFRESH_INTERVAL*1000, n_intervals=0),
    ], style={"fontFamily":"Arial","padding":"20px","background":"#f8f9fa"})
    
    @app.callback([Output("kpi-cycles","children"),Output("kpi-publish","children"),Output("kpi-errors","children"),
                   Output("kpi-next","children"),Output("last-update","children"),Output("chart-duration","figure"),
                   Output("chart-publish","figure"),Output("chart-vibration","figure"),Output("error-list","children")],
                  [Input("interval","n_intervals")])
    def update(n):
        parser.parse_recent(); s = parser.get_summary()
        lu = f"Actualizado: {s['last_update'].strftime('%H:%M:%S')}" if s["last_update"] else "Esperando datos..."
        # Charts
        fig_dur = go.Figure(); fig_pub = go.Figure(); fig_vib = go.Figure()
        if parser.metrics["cycles"]:
            fig_dur.add_trace(go.Scatter(x=[c["ts"] for c in parser.metrics["cycles"] if c.get("ts")], 
                                         y=[c["duration"] for c in parser.metrics["cycles"]], mode="lines+markers", line=dict(color="#3498db")))
            fig_dur.update_layout(title="Segundos por ciclo", height=280, margin=dict(t=30,b=30,l=30,r=10))
        if parser.metrics["publishes"]:
            cum, t, ok = [], 0, 0
            for p in parser.metrics["publishes"]:
                t+=1; ok += 1 if p["status"]==201 else 0; cum.append((p.get("ts"), ok/t*100))
            fig_pub.add_trace(go.Scatter(x=[x[0] for x in cum if x[0]], y=[x[1] for x in cum], mode="lines", line=dict(color="#2ecc71")))
            fig_pub.update_layout(title="Tasa de éxito %", yaxis_range=[0,100], height=280, margin=dict(t=30,b=30,l=30,r=10))
        if parser.metrics["vibrations"]:
            fig_vib.add_trace(go.Scatter(x=[v["ts"] for v in parser.metrics["vibrations"] if v.get("ts")], 
                                         y=[v["value"] for v in parser.metrics["vibrations"]], mode="lines+markers", line=dict(color="#9b59b6")))
            fig_vib.update_layout(title="Platform Awareness", height=280, margin=dict(t=30,b=30,l=30,r=10))
        # Errors
        errs = [html.Div(f"[{e['ts'].strftime('%H:%M') if e.get('ts') else '?'}] {e['msg']}", 
                        style={"padding":"4px","borderBottom":"1px solid #eee","color":"#e74c3c"}) 
               for e in reversed(parser.metrics["errors"][-8:])] or [html.Div("✅ Sin errores recientes", style={"color":"#2ecc71","padding":"10px"})]
        return (f"{s['cycles']}", f"{s['publish_rate']:.1f}%", f"{s['errors']}", s["next_cycle"] or "N/A", lu, 
                fig_dur, fig_pub, fig_vib, errs)
    return app

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port",type=int,default=DEFAULT_PORT)
    ap.add_argument("--log-path",type=Path,default=DEFAULT_LOG_PATH); args = ap.parse_args()
    if not args.log_path.exists(): print(f"⚠️ Log no encontrado: {args.log_path}")
    parser = LogParser(args.log_path); app = create_app(parser)
    print(f"🚀 Dashboard en http://localhost:{args.port}"); print(f"📊 Logs: {args.log_path.absolute()}")
    print(f"🔄 Refresh: {REFRESH_INTERVAL}s | Ctrl+C para salir"); app.run(port=args.port, debug=False)

if __name__ == "__main__": main()
