#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trabalho 07 - Sistemas Distribuídos (UFPI)
Aluno: Leonardo Virgulino Rodrigues Carvalho
Contexto 1: Servidor Web
"""

import csv
import json
import math
import os
import random
import subprocess
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
FIGURES_DIR = os.path.join(BASE_DIR, "figures")
ARTIGO_FIG_DIR = os.path.join(BASE_DIR, "artigo", "figures")

for d in (RESULTS_DIR, FIGURES_DIR, ARTIGO_FIG_DIR):
    os.makedirs(d, exist_ok=True)


def evaluate_spn_steady_state(ar: float, p_ws: int, c_fila: int, ts: float = 20.0) -> Dict[str, float]:
    """Calcula as métricas do modelo SPN em regime estacionário."""
    ad = 1.0 / ar
    mu = 1.0 / ts  # taxa de serviço por servidor (req/ms)
    max_n = p_ws + c_fila

    # Cálculo das probabilidades estacionárias pi[n] para 0 <= n <= max_n
    # usando log-soma para estabilidade numérica
    log_weights = [0.0] * (max_n + 1)
    for n in range(1, max_n + 1):
        active_servers = min(n, p_ws)
        rate_service = active_servers * mu
        log_weights[n] = log_weights[n - 1] + math.log(ar / rate_service)

    max_log = max(log_weights)
    weights = [math.exp(lw - max_log) for lw in log_weights]
    total_weight = sum(weights)
    pi = [w / total_weight for w in weights]

    # Esperanças dos lugares E{#Place} e Probabilidades P{cond}
    e_p_trans = sum(min(n, p_ws) * pi[n] for n in range(max_n + 1))
    e_p_fila_web = sum(max(0, n - p_ws) * pi[n] for n in range(max_n + 1))
    e_p_transproc = p_ws - e_p_trans
    e_p_transcap = c_fila - e_p_fila_web

    # P{(#P_Fila > 0) and (#P_TransCap == 0)} em chegada Poisson (PASTA) = P{#P_TransCap == 0} = pi[max_n]
    p_drop = pi[max_n]

    # Expressões das 6 métricas conforme definidas na Etapa 3:
    # 1. Utilization (U) [%] = (E{#P_Trans} / P_WS) * 100
    u_pct = (e_p_trans / p_ws) * 100.0

    # 2. Drop Probability (DP) [%] = P{#P_TransCap == 0} * 100
    dp_pct = p_drop * 100.0

    # 3. Throughput (TP) [req/ms e req/s] = E{#P_Trans} / TS
    tp_ms = e_p_trans / ts
    tp_s = tp_ms * 1000.0

    # 4. Mean Queue Time (MQT) [ms] = (E{#P_Fila_Web} * AD) / (1 - P_drop)
    mqt_ms = (e_p_fila_web * ad) / (1.0 - p_drop)

    # 5. Mean Processing Time (MPT) [ms] = (E{#P_Trans} * AD) / (1 - P_drop)
    mpt_ms = (e_p_trans * ad) / (1.0 - p_drop)

    # 6. Mean Response Time (MRT) [ms] = ((E{#P_Fila_Web} + E{#P_Trans}) * AD) / (1 - P_drop)
    mrt_ms = ((e_p_fila_web + e_p_trans) * ad) / (1.0 - p_drop)

    return {
        "AR": round(ar, 4),
        "AD": round(ad, 4),
        "P_WS": p_ws,
        "C_FILA": c_fila,
        "TS": round(ts, 2),
        "E_P_Fila_Web": round(e_p_fila_web, 4),
        "E_P_Trans": round(e_p_trans, 4),
        "E_P_TransCap": round(e_p_transcap, 4),
        "E_P_TransProc": round(e_p_transproc, 4),
        "U": round(u_pct, 2),
        "DP": round(dp_pct, 2),
        "TP_ms": round(tp_ms, 4),
        "TP_s": round(tp_s, 2),
        "MQT": round(mqt_ms, 2),
        "MPT": round(mpt_ms, 2),
        "MRT": round(mrt_ms, 2),
    }


def simulate_spn_token_game(
    ar: float,
    p_ws: int,
    c_fila: int,
    ts: float = 20.0,
    horizon_ms: float = 200000.0,
    seed: int = 42,
) -> Dict[str, float]:
    """
    Simulador Estocástico de Eventos Discretos (Token Game idêntico ao motor do Jupiter Analytics).
    Usado para validar a concordância entre simulação estocástica e solução analítica estacionária.
    """
    rng = random.Random(seed)
    ad = 1.0 / ar
    mu = 1.0 / ts

    # Estado inicial dos lugares tangíveis
    p_trans = 0
    p_fila_web = 0
    p_transproc = p_ws
    p_transcap = c_fila

    t = 0.0
    area_p_trans = 0.0
    area_p_fila_web = 0.0
    area_full = 0.0

    arrivals = 0
    drops = 0

    while t < horizon_ms:
        rate_arr = ar
        rate_srv = p_trans * mu
        total_rate = rate_arr + rate_srv
        dt = rng.expovariate(total_rate)
        if t + dt > horizon_ms:
            dt = horizon_ms - t

        # Acumula integrais no tempo para E{#Place} e P{#P_TransCap == 0}
        area_p_trans += p_trans * dt
        area_p_fila_web += p_fila_web * dt
        if p_transcap == 0:
            area_full += dt

        t += dt
        if t >= horizon_ms:
            break

        # Disparo da transição vencedora (Race Policy)
        if rng.random() < (rate_arr / total_rate):
            # Disparo de AD -> coloca ficha em P_Fila
            arrivals += 1
            # Disparo imediato: T1 (se P_TransCap > 0) ou T_Descarte (se P_TransCap == 0)
            if p_transcap > 0:
                p_fila_web += 1
                p_transcap -= 1
                # Verifica T2 (imediata): se há servidor livre em P_TransProc
                if p_transproc > 0 and p_fila_web > 0:
                    p_fila_web -= 1
                    p_transcap += 1
                    p_transproc -= 1
                    p_trans += 1
            else:
                drops += 1
        else:
            # Disparo de T_Trans -> conclui 1 processamento e devolve servidor a P_TransProc
            p_trans -= 1
            p_transproc += 1
            # Verifica T2 (imediata): se há requisição aguardando em P_Fila_Web
            if p_fila_web > 0 and p_transproc > 0:
                p_fila_web -= 1
                p_transcap += 1
                p_transproc -= 1
                p_trans += 1

    e_p_trans = area_p_trans / horizon_ms
    e_p_fila_web = area_p_fila_web / horizon_ms
    p_drop = area_full / horizon_ms

    u_pct = (e_p_trans / p_ws) * 100.0
    dp_pct = p_drop * 100.0
    tp_ms = e_p_trans / ts
    tp_s = tp_ms * 1000.0
    mqt_ms = (e_p_fila_web * ad) / (1.0 - p_drop)
    mpt_ms = (e_p_trans * ad) / (1.0 - p_drop)
    mrt_ms = ((e_p_fila_web + e_p_trans) * ad) / (1.0 - p_drop)

    return {
        "U_sim": round(u_pct, 2),
        "DP_sim": round(dp_pct, 2),
        "TP_s_sim": round(tp_s, 2),
        "MQT_sim": round(mqt_ms, 2),
        "MPT_sim": round(mpt_ms, 2),
        "MRT_sim": round(mrt_ms, 2),
    }


# ==============================================================================
# 2. EXECUÇÃO DOS 4 EXPERIMENTOS OBRIGATÓRIOS (E1, E2, E3, E4)
# ==============================================================================

def save_csv(filepath: str, rows: List[Dict]):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_all_experiments():
    # Parâmetros do Cenário de Referência (Baseline)
    # TS = 20 ms (taxa por núcleo mu = 0.05 req/ms = 50 req/s)
    # P_WS = 8 núcleos (capacidade nominal = 8 * 0.05 = 0.40 req/ms = 400 req/s)
    # C_FILA = 20 vagas na fila de espera
    # AR_REF = 0.40 req/ms (AD = 2.5 ms)
    TS_REF = 20.0
    P_WS_REF = 8
    C_FILA_REF = 20
    AR_REF = 0.40

    # --------------------------------------------------------------------------
    # E1 - Taxa de chegada (5 níveis principais + malha fina para curvas)
    # 5 níveis: AR in {0.10, 0.25, 0.40, 0.55, 0.70} req/ms
    # --------------------------------------------------------------------------
    e1_levels = [0.10, 0.25, 0.40, 0.55, 0.70]
    e1_rows = []
    for i, ar in enumerate(e1_levels, 1):
        res = evaluate_spn_steady_state(ar=ar, p_ws=P_WS_REF, c_fila=C_FILA_REF, ts=TS_REF)
        sim = simulate_spn_token_game(ar=ar, p_ws=P_WS_REF, c_fila=C_FILA_REF, ts=TS_REF)
        row = {"Experimento": f"E1.{i}", "Descricao": f"Demanda AR={ar:.2f} req/ms", **res, **sim}
        e1_rows.append(row)
    save_csv(os.path.join(RESULTS_DIR, "E1_taxa_chegada.csv"), e1_rows)

    # Malha fina de AR (0.05 a 0.80 com passo 0.05) para gráficos suaves
    ar_grid = [round(0.05 * k, 2) for k in range(1, 17)]
    e1_curve = [evaluate_spn_steady_state(ar=ar, p_ws=P_WS_REF, c_fila=C_FILA_REF, ts=TS_REF) for ar in ar_grid]
    save_csv(os.path.join(RESULTS_DIR, "E1_curva_completa.csv"), e1_curve)

    # --------------------------------------------------------------------------
    # E2 - Capacidade de processamento (3 configurações de recursos)
    # P_WS in {4 (2 máq x 2 núcleos), 8 (4 máq x 2 núcleos), 12 (6 máq x 2 núcleos)}
    # Mantendo AR = 0.40 req/ms e C_FILA = 20 constantes
    # --------------------------------------------------------------------------
    e2_configs = [
        ("E2.1 (Config. A - 4 núcleos)", 4),
        ("E2.2 (Config. B - 8 núcleos)", 8),
        ("E2.3 (Config. C - 12 núcleos)", 12),
    ]
    e2_rows = []
    e2_curves = {}
    for label, p_ws in e2_configs:
        res = evaluate_spn_steady_state(ar=AR_REF, p_ws=p_ws, c_fila=C_FILA_REF, ts=TS_REF)
        sim = simulate_spn_token_game(ar=AR_REF, p_ws=p_ws, c_fila=C_FILA_REF, ts=TS_REF)
        e2_rows.append({"Experimento": label.split()[0], "Descricao": label, **res, **sim})
        e2_curves[p_ws] = [evaluate_spn_steady_state(ar=ar, p_ws=p_ws, c_fila=C_FILA_REF, ts=TS_REF) for ar in ar_grid]
    save_csv(os.path.join(RESULTS_DIR, "E2_capacidade_processamento.csv"), e2_rows)

    # --------------------------------------------------------------------------
    # E3 - Capacidade da fila (3 limites de capacidade)
    # C_FILA in {10, 20, 40} vagas
    # Mantendo AR = 0.40 req/ms e P_WS = 8 constantes
    # --------------------------------------------------------------------------
    e3_configs = [
        ("E3.1 (Fila Curta - C_FILA=10)", 10),
        ("E3.2 (Fila Média - C_FILA=20)", 20),
        ("E3.3 (Fila Longa - C_FILA=40)", 40),
    ]
    e3_rows = []
    e3_curves = {}
    for label, c_fila in e3_configs:
        res = evaluate_spn_steady_state(ar=AR_REF, p_ws=P_WS_REF, c_fila=c_fila, ts=TS_REF)
        sim = simulate_spn_token_game(ar=AR_REF, p_ws=P_WS_REF, c_fila=c_fila, ts=TS_REF)
        e3_rows.append({"Experimento": label.split()[0], "Descricao": label, **res, **sim})
        e3_curves[c_fila] = [evaluate_spn_steady_state(ar=ar, p_ws=P_WS_REF, c_fila=c_fila, ts=TS_REF) for ar in ar_grid]
    save_csv(os.path.join(RESULTS_DIR, "E3_capacidade_fila.csv"), e3_rows)

    # --------------------------------------------------------------------------
    # E4 - Demanda e recursos combinados (3 cenários combinados)
    # E4.1: Sobrecarga Crítica (Alta demanda AR=0.55, Recursos reduzidos P_WS=6, C_FILA=10)
    # E4.2: Dimensionamento Equilibrado / Recomendado (Alta demanda AR=0.55, P_WS=12, C_FILA=20)
    # E4.3: Superdimensionado de Alto Custo (Alta demanda AR=0.55, P_WS=16, C_FILA=40)
    # --------------------------------------------------------------------------
    e4_configs = [
        ("E4.1", "C1: Subdimensionado (AR=0.55, P_WS=6, C_FILA=10)", 0.55, 6, 10),
        ("E4.2", "C2: Equilibrado/Recomendado (AR=0.55, P_WS=12, C_FILA=20)", 0.55, 12, 20),
        ("E4.3", "C3: Superdimensionado (AR=0.55, P_WS=16, C_FILA=40)", 0.55, 16, 40),
    ]
    e4_rows = []
    for code, desc, ar, p_ws, c_fila in e4_configs:
        res = evaluate_spn_steady_state(ar=ar, p_ws=p_ws, c_fila=c_fila, ts=TS_REF)
        sim = simulate_spn_token_game(ar=ar, p_ws=p_ws, c_fila=c_fila, ts=TS_REF)
        e4_rows.append({"Experimento": code, "Descricao": desc, **res, **sim})
    save_csv(os.path.join(RESULTS_DIR, "E4_cenarios_combinados.csv"), e4_rows)

    # Tabela Consolidada com todos os 14 experimentos (5 E1 + 3 E2 + 3 E3 + 3 E4)
    consolidated = e1_rows + e2_rows + e3_rows + e4_rows
    save_csv(os.path.join(RESULTS_DIR, "tabela_consolidada.csv"), consolidated)

    return {
        "ar_grid": ar_grid,
        "e1_rows": e1_rows,
        "e1_curve": e1_curve,
        "e2_rows": e2_rows,
        "e2_curves": e2_curves,
        "e3_rows": e3_rows,
        "e3_curves": e3_curves,
        "e4_rows": e4_rows,
        "consolidated": consolidated,
    }


# Geração das figuras em PDF e PNG

def ps_escape(text: str) -> str:
    """Converte caracteres acentuados UTF-8 para octal ISOLatin1Encoding no PostScript."""
    out = []
    for ch in text:
        if ch in ("(", ")", "\\"):
            out.append("\\" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            b = ch.encode("latin1", errors="replace")[0]
            out.append(f"\\{b:03o}")
    return "".join(out)


def compile_ps_to_pdf_and_png(ps_content: str, basename: str, width_pt: int, height_pt: int):
    """Converte um arquivo PostScript para PDF vetorial e PNG de 300 DPI usando Ghostscript."""
    ps_path = os.path.join(FIGURES_DIR, f"{basename}.ps")
    pdf_path = os.path.join(FIGURES_DIR, f"{basename}.pdf")
    png_path = os.path.join(FIGURES_DIR, f"{basename}.png")
    art_pdf_path = os.path.join(ARTIGO_FIG_DIR, f"{basename}.pdf")
    art_png_path = os.path.join(ARTIGO_FIG_DIR, f"{basename}.png")

    with open(ps_path, "w", encoding="latin1") as f:
        f.write(ps_content)

    subprocess.run(
        [
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            f"-dDEVICEWIDTHPOINTS={width_pt}", f"-dDEVICEHEIGHTPOINTS={height_pt}",
            "-dFIXEDMEDIA", f"-sOutputFile={pdf_path}", ps_path,
        ],
        check=True,
    )
    subprocess.run(
        [
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r300",
            f"-dDEVICEWIDTHPOINTS={width_pt}", f"-dDEVICEHEIGHTPOINTS={height_pt}",
            "-dFIXEDMEDIA", f"-sOutputFile={png_path}", ps_path,
        ],
        check=True,
    )
    # Copia também para artigo/figures/
    with open(pdf_path, "rb") as src, open(art_pdf_path, "wb") as dst:
        dst.write(src.read())
    with open(png_path, "rb") as src, open(art_png_path, "wb") as dst:
        dst.write(src.read())
    os.remove(ps_path)


def ps_header(width_pt: int, height_pt: int) -> str:
    return f"""%!PS-Adobe-3.0
%%BoundingBox: 0 0 {width_pt} {height_pt}
%%Pages: 1
%%Page: 1 1
/reencodeISO {{
  dup length dict begin
  {{1 index /FID ne {{def}} {{pop pop}} ifelse}} forall
  /Encoding ISOLatin1Encoding def
  currentdict end
  definefont pop
}} bind def
/Helvetica findfont /Helvetica-ISO exch reencodeISO
/Helvetica-Bold findfont /Helvetica-Bold-ISO exch reencodeISO
/Helvetica-Oblique findfont /Helvetica-Oblique-ISO exch reencodeISO
/F {{ /Helvetica-ISO findfont exch scalefont setfont }} bind def
/FB {{ /Helvetica-Bold-ISO findfont exch scalefont setfont }} bind def
/FI {{ /Helvetica-Oblique-ISO findfont exch scalefont setfont }} bind def
/cshow {{ dup stringwidth pop 2 div neg 0 rmoveto show }} bind def
/rshow {{ dup stringwidth pop neg 0 rmoveto show }} bind def
1 setlinejoin 1 setlinecap
0.99 0.99 0.99 setrgbcolor 0 0 {width_pt} {height_pt} rectfill
"""


def draw_marker_ps(x: float, y: float, style: int, size: float = 3.2) -> str:
    if style == 0:  # circle
        return f"newpath {x:.2f} {y:.2f} {size:.2f} 0 360 arc fill\n"
    elif style == 1:  # square
        s = size * 0.9
        return f"{x-s:.2f} {y-s:.2f} {2*s:.2f} {2*s:.2f} rectfill\n"
    elif style == 2:  # triangle
        s = size * 1.15
        return f"newpath {x:.2f} {y+s:.2f} moveto {x-s:.2f} {y-s*0.8:.2f} lineto {x+s:.2f} {y-s*0.8:.2f} lineto closepath fill\n"
    else:  # diamond
        s = size * 1.15
        return f"newpath {x:.2f} {y+s:.2f} moveto {x-s:.2f} {y:.2f} lineto {x:.2f} {y-s:.2f} lineto {x+s:.2f} {y:.2f} lineto closepath fill\n"


def draw_subplot_ps(
    ox: float, oy: float, w: float, h: float,
    x_vals: List[float],
    series_list: List[Tuple[str, List[float], Tuple[float, float, float], int]],
    x_min: float, x_max: float, x_step: float,
    y_min: float, y_max: float, y_step: float,
    xlabel: str, ylabel: str, title: str,
    highlight_xs: List[float] = None,
    legend_pos: str = "tl",
) -> str:
    ps = []
    # Fundo branco da área do gráfico
    ps.append(f"1 1 1 setrgbcolor {ox:.1f} {oy:.1f} {w:.1f} {h:.1f} rectfill")

    # Grid horizontal e ticks Y
    y_val = y_min
    while y_val <= y_max + 1e-6:
        py = oy + (y_val - y_min) / (y_max - y_min) * h
        ps.append(f"0.88 0.88 0.88 setrgbcolor 0.5 setlinewidth [2 2] 0 setdash")
        ps.append(f"newpath {ox:.1f} {py:.2f} moveto {ox+w:.1f} {py:.2f} lineto stroke")
        ps.append("[] 0 setdash 0.15 0.15 0.15 setrgbcolor 8.5 F")
        lbl = f"{int(round(y_val))}" if abs(y_step) >= 1 else f"{y_val:.2f}".replace(".", ",")
        ps.append(f"{ox-5:.1f} {py-3:.2f} moveto ({ps_escape(lbl)}) rshow")
        y_val += y_step

    # Grid vertical e ticks X
    x_val = x_min
    while x_val <= x_max + 1e-6:
        px = ox + (x_val - x_min) / (x_max - x_min) * w
        ps.append(f"0.88 0.88 0.88 setrgbcolor 0.5 setlinewidth [2 2] 0 setdash")
        ps.append(f"newpath {px:.2f} {oy:.1f} moveto {px:.2f} {oy+h:.1f} lineto stroke")
        ps.append("[] 0 setdash 0.15 0.15 0.15 setrgbcolor 8.5 F")
        lbl = f"{x_val:.2f}".replace(".", ",")
        ps.append(f"{px:.2f} {oy-12:.1f} moveto ({ps_escape(lbl)}) cshow")
        x_val += x_step

    # Destaque vertical para os 5 pontos de E1 (se fornecido)
    if highlight_xs:
        for hx in highlight_xs:
            px = ox + (hx - x_min) / (x_max - x_min) * w
            ps.append("0.75 0.82 0.92 setrgbcolor 0.8 setlinewidth [3 2] 0 setdash")
            ps.append(f"newpath {px:.2f} {oy:.1f} moveto {px:.2f} {oy+h:.1f} lineto stroke")
        ps.append("[] 0 setdash")

    # Bordas dos eixos
    ps.append(f"0.1 0.1 0.1 setrgbcolor 1.0 setlinewidth")
    ps.append(f"{ox:.1f} {oy:.1f} {w:.1f} {h:.1f} rectstroke")

    # Séries de dados
    for name, y_vals, (r, g, b), mstyle in series_list:
        ps.append(f"{r:.2f} {g:.2f} {b:.2f} setrgbcolor 1.6 setlinewidth")
        pts = []
        for xv, yv in zip(x_vals, y_vals):
            px = ox + (xv - x_min) / (x_max - x_min) * w
            yc = max(y_min, min(y_max, yv))
            py = oy + (yc - y_min) / (y_max - y_min) * h
            pts.append((px, py))
        if pts:
            ps.append(f"newpath {pts[0][0]:.2f} {pts[0][1]:.2f} moveto")
            for px, py in pts[1:]:
                ps.append(f"{px:.2f} {py:.2f} lineto")
            ps.append("stroke")
            for px, py in pts:
                ps.append(draw_marker_ps(px, py, mstyle, 2.8))

    # Legenda (se houver mais de 1 série ou nome explícito)
    if len(series_list) >= 1 and series_list[0][0]:
        leg_h = 13 * len(series_list) + 6
        leg_w = max(len(s[0]) for s in series_list) * 4.7 + 26
        if legend_pos == "br":
            lx = ox + w - leg_w - 8
            ly = oy + 8
        else:
            lx = ox + 8
            ly = oy + h - leg_h - 6
        ps.append(f"1 1 1 setrgbcolor {lx:.1f} {ly:.1f} {leg_w:.1f} {leg_h:.1f} rectfill")
        ps.append(f"0.4 0.4 0.4 setrgbcolor 0.6 setlinewidth {lx:.1f} {ly:.1f} {leg_w:.1f} {leg_h:.1f} rectstroke")
        for idx, (name, _, (r, g, b), mstyle) in enumerate(series_list):
            row_y = ly + leg_h - 11 - idx * 13
            ps.append(f"{r:.2f} {g:.2f} {b:.2f} setrgbcolor 1.5 setlinewidth")
            ps.append(f"newpath {lx+5:.1f} {row_y:.1f} moveto {lx+19:.1f} {row_y:.1f} lineto stroke")
            ps.append(draw_marker_ps(lx + 12, row_y, mstyle, 2.6))
            ps.append(f"0.1 0.1 0.1 setrgbcolor 8.0 F {lx+23:.1f} {row_y-3:.1f} moveto ({ps_escape(name)}) show")

    # Rótulos X, Y e Título
    ps.append(f"0.05 0.05 0.05 setrgbcolor 9.5 FB {ox+w/2:.1f} {oy-26:.1f} moveto ({ps_escape(xlabel)}) cshow")
    ps.append(f"0.05 0.05 0.05 setrgbcolor 10.0 FB {ox+w/2:.1f} {oy+h+7:.1f} moveto ({ps_escape(title)}) cshow")
    ps.append(f"gsave {ox-32:.1f} {oy+h/2:.1f} translate 90 rotate 0 0 moveto 9.5 FB ({ps_escape(ylabel)}) cshow grestore")
    return "\n".join(ps) + "\n"


def generate_architecture_and_spn_diagrams():
    """Gera os diagramas vetoriais da Arquitetura (Fig. 1) e do Modelo SPN (Fig. 2)."""
    # --------------------------------------------------------------------------
    # FIGURA 1: Arquitetura do Sistema de Servidor Web
    # --------------------------------------------------------------------------
    W, H = 560, 215
    ps = [ps_header(W, H)]
    # Caixas das camadas
    # Camada 1: Clientes (Internet)
    ps.append("0.93 0.96 1.00 setrgbcolor 14 25 145 165 rectfill")
    ps.append("0.20 0.40 0.70 setrgbcolor 1.2 setlinewidth 14 25 145 165 rectstroke")
    ps.append("0.10 0.25 0.50 setrgbcolor 10 FB 86 175 moveto (1. Clientes Web (Internet)) cshow")

    for i, cy in enumerate([135, 95, 55], 1):
        ps.append(f"1 1 1 setrgbcolor 32 {cy-12} 108 26 rectfill")
        ps.append(f"0.25 0.45 0.75 setrgbcolor 1.0 setlinewidth 32 {cy-12} 108 26 rectstroke")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 8.5 FB 86 {cy-3} moveto (Cliente HTTP #{i}) cshow")

    # Camada 2: Admissão & Load Balancer (NGINX)
    ps.append("0.94 0.98 0.94 setrgbcolor 185 25 165 165 rectfill")
    ps.append("0.20 0.60 0.30 setrgbcolor 1.2 setlinewidth 185 25 165 165 rectstroke")
    ps.append("0.10 0.40 0.18 setrgbcolor 10 FB 267 175 moveto (2. Admissão e Fila (Proxy)) cshow")

    # Caixa Gateway/Proxy
    ps.append("1 1 1 setrgbcolor 200 108 135 46 rectfill")
    ps.append("0.20 0.60 0.30 setrgbcolor 1.1 setlinewidth 200 108 135 46 rectstroke")
    ps.append("0.1 0.1 0.1 setrgbcolor 9 FB 267 134 moveto (Balanceador de Carga) cshow")
    ps.append("0.25 0.25 0.25 setrgbcolor 8 F 267 119 moveto (Buffer Limitado: C_FILA) cshow")

    # Caixa Descarte
    ps.append("1.00 0.92 0.92 setrgbcolor 205 38 125 36 rectfill")
    ps.append("0.75 0.20 0.20 setrgbcolor 1.0 setlinewidth 205 38 125 36 rectstroke")
    ps.append("0.65 0.10 0.10 setrgbcolor 8.5 FB 267 58 moveto (Descarte HTTP 503) cshow")
    ps.append("0.40 0.10 0.10 setrgbcolor 7.8 F 267 45 moveto (se Fila Cheia: DP) cshow")

    # Seta Proxy -> Descarte
    ps.append("0.75 0.20 0.20 setrgbcolor 1.2 setlinewidth newpath 267 108 moveto 267 74 lineto stroke")
    ps.append("newpath 267 74 moveto 264 81 lineto 270 81 lineto closepath fill")

    # Camada 3: Cluster de Servidores Web
    ps.append("0.98 0.95 0.90 setrgbcolor 376 25 170 165 rectfill")
    ps.append("0.75 0.45 0.15 setrgbcolor 1.2 setlinewidth 376 25 170 165 rectstroke")
    ps.append("0.55 0.30 0.05 setrgbcolor 10 FB 461 175 moveto (3. Pool de Servidores Web) cshow")

    for i, sy in enumerate([138, 100, 62], 1):
        ps.append(f"1 1 1 setrgbcolor 394 {sy-13} 134 28 rectfill")
        ps.append(f"0.75 0.45 0.15 setrgbcolor 1.0 setlinewidth 394 {sy-13} 134 28 rectstroke")
        lbl = f"Servidor Web #{i} (Núcleos)" if i < 3 else "Servidor Web #M (P_WS)"
        ps.append(f"0.1 0.1 0.1 setrgbcolor 8.5 FB 461 {sy-2} moveto ({ps_escape(lbl)}) cshow")
    ps.append("0.3 0.3 0.3 setrgbcolor 8 FI 461 34 moveto (Tempo de Serviço: TS = 20 ms) cshow")

    # Setas Clientes -> Balanceador
    ps.append("0.20 0.40 0.70 setrgbcolor 1.2 setlinewidth")
    for cy in [135, 95, 55]:
        ps.append(f"newpath 140 {cy} moveto 200 131 lineto stroke")
    ps.append("newpath 200 131 moveto 192 134 lineto 193 127 lineto closepath fill")
    ps.append("0.10 0.25 0.50 setrgbcolor 8 FB 168 148 moveto (Taxa AR) cshow")

    # Setas Balanceador -> Servidores Web
    ps.append("0.20 0.60 0.30 setrgbcolor 1.2 setlinewidth")
    for sy in [138, 100, 62]:
        ps.append(f"newpath 335 131 moveto 394 {sy} lineto stroke")
        ps.append(f"newpath 394 {sy} moveto 386 {sy+3} lineto 386 {sy-3} lineto closepath fill")

    ps.append("0.1 0.1 0.1 setrgbcolor 10.5 FB 280 7 moveto (Arquitetura do Sistema de Servidor Web com Controle de Admissão e Fila Limitada) cshow")
    ps.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps), "fig_arquitetura_web", W, H)

    # --------------------------------------------------------------------------
    # FIGURA 2: Modelo SPN no padrão Jupiter / Mercury (PASID)
    # --------------------------------------------------------------------------
    W2, H2 = 580, 230
    ps2 = [ps_header(W2, H2)]

    # Sub-caixas tracejadas de camadas
    ps2.append("0.95 0.97 1.00 setrgbcolor 12 20 185 190 rectfill")
    ps2.append("0.40 0.55 0.80 setrgbcolor 0.9 setlinewidth [4 2] 0 setdash 12 20 185 190 rectstroke [] 0 setdash")
    ps2.append("0.15 0.30 0.60 setrgbcolor 9.5 FB 104 196 moveto (Camada de Admissão (Internet)) cshow")

    ps2.append("0.96 0.98 0.95 setrgbcolor 205 20 363 190 rectfill")
    ps2.append("0.35 0.65 0.40 setrgbcolor 0.9 setlinewidth [4 2] 0 setdash 205 20 363 190 rectstroke [] 0 setdash")
    ps2.append("0.15 0.45 0.20 setrgbcolor 9.5 FB 386 196 moveto (Camada de Servidor Web (Fila FCFS + Pool de Servidores)) cshow")

    def draw_place(cx, cy, name, tok_label, label_above=False):
        r = 16
        ps2.append(f"1 1 1 setrgbcolor newpath {cx} {cy} {r} 0 360 arc fill")
        ps2.append(f"0.1 0.1 0.1 setrgbcolor 1.3 setlinewidth newpath {cx} {cy} {r} 0 360 arc stroke")
        if tok_label == "1":
            ps2.append(f"0.1 0.1 0.1 setrgbcolor newpath {cx} {cy} 4 0 360 arc fill")
        elif tok_label:
            ps2.append(f"0.1 0.1 0.1 setrgbcolor 7.8 FB {cx} {cy-3} moveto ({ps_escape(tok_label)}) cshow")
        ly = cy + r + 7 if label_above else cy - r - 12
        ps2.append(f"0.05 0.05 0.05 setrgbcolor 8.2 FB {cx} {ly} moveto ({ps_escape(name)}) cshow")

    def draw_trans(tx, ty, name, timed=True, sublabel=""):
        tw, th = (9, 32) if timed else (5, 32)
        if timed:
            ps2.append(f"1 1 1 setrgbcolor {tx-tw/2:.1f} {ty-th/2:.1f} {tw} {th} rectfill")
            ps2.append(f"0.1 0.1 0.1 setrgbcolor 1.3 setlinewidth {tx-tw/2:.1f} {ty-th/2:.1f} {tw} {th} rectstroke")
        else:
            ps2.append(f"0.1 0.1 0.1 setrgbcolor {tx-tw/2:.1f} {ty-th/2:.1f} {tw} {th} rectfill")
        ps2.append(f"0.05 0.05 0.05 setrgbcolor 8.2 FB {tx} {ty-th/2-12:.1f} moveto ({ps_escape(name)}) cshow")
        if sublabel:
            ps2.append(f"0.30 0.30 0.30 setrgbcolor 7.2 FI {tx} {ty-th/2-21:.1f} moveto ({ps_escape(sublabel)}) cshow")

    def draw_arrow(x1, y1, x2, y2, inhibitor=False):
        ps2.append(f"0.15 0.15 0.15 setrgbcolor 1.1 setlinewidth newpath {x1:.1f} {y1:.1f} moveto {x2:.1f} {y2:.1f} lineto stroke")
        ang = math.atan2(y2 - y1, x2 - x1)
        if inhibitor:
            cx = x2 - 4.0 * math.cos(ang)
            cy = y2 - 4.0 * math.sin(ang)
            ps2.append(f"1 1 1 setrgbcolor newpath {cx:.1f} {cy:.1f} 3.2 0 360 arc fill")
            ps2.append(f"0.15 0.15 0.15 setrgbcolor 1.0 setlinewidth newpath {cx:.1f} {cy:.1f} 3.2 0 360 arc stroke")
        else:
            bx = x2 - 6.5 * math.cos(ang)
            by = y2 - 6.5 * math.sin(ang)
            px = -3.0 * math.sin(ang)
            py = 3.0 * math.cos(ang)
            ps2.append(
                f"0.15 0.15 0.15 setrgbcolor newpath {x2:.1f} {y2:.1f} moveto "
                f"{bx+px:.1f} {by+py:.1f} lineto {bx-px:.1f} {by-py:.1f} lineto closepath fill"
            )

    # Coordenadas principais (linha central y = 78)
    y_main = 78
    y_top = 152

    # Lugares e Transições
    draw_place(42, y_main, "P_Chegada", "1")
    draw_trans(95, y_main, "AD", timed=True, sublabel="1/AR")
    draw_place(148, y_main, "P_Fila", "0")
    draw_trans(218, y_main, "T1", timed=False, sublabel="Imed.")
    draw_place(285, y_main, "P_Fila_Web", "0")
    draw_trans(355, y_main, "T2", timed=False, sublabel="Imed.")
    draw_place(425, y_main, "P_Trans", "0")
    draw_trans(495, y_main, "T_Trans", timed=True, sublabel="TS (Inf.Srv)")

    # Lugares de Capacidade no topo
    draw_place(285, y_top, "P_TransCap", "C_FILA", label_above=True)
    draw_place(425, y_top, "P_TransProc", "P_WS", label_above=True)

    # Arcos horizontais principais
    draw_arrow(58, y_main + 4, 90, y_main + 4)
    draw_arrow(90, y_main - 4, 58, y_main - 4)
    draw_arrow(100, y_main, 132, y_main)
    draw_arrow(164, y_main, 215, y_main)
    draw_arrow(221, y_main, 269, y_main)
    draw_arrow(301, y_main, 352, y_main)
    draw_arrow(358, y_main, 409, y_main)
    draw_arrow(441, y_main, 490, y_main)

    # Arcos de capacidade da fila (P_TransCap <-> T1, T2)
    draw_arrow(273, y_top - 11, 220, y_main + 16)
    draw_arrow(353, y_main + 16, 297, y_top - 11)

    # Arcos de capacidade de processamento (P_TransProc <-> T2, T_Trans)
    draw_arrow(413, y_top - 11, 357, y_main + 16)
    draw_arrow(495, y_main + 16, 437, y_top - 11)

    ps2.append("0.05 0.05 0.05 setrgbcolor 10.0 FB 290 5 moveto (Modelo de Rede de Petri Estocástica (SPN) para o Sistema de Servidor Web) cshow")
    ps2.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps2), "fig_modelo_spn", W2, H2)


def generate_experiment_figures(data: Dict):
    ar_grid = data["ar_grid"]
    e1_curve = data["e1_curve"]
    e1_levels = [0.10, 0.25, 0.40, 0.55, 0.70]

    # Cores padrão (azul, vermelho, verde, roxo)
    c_blue = (0.12, 0.38, 0.72)
    c_red = (0.82, 0.18, 0.18)
    c_green = (0.15, 0.60, 0.28)
    c_orange = (0.88, 0.48, 0.08)

    # --------------------------------------------------------------------------
    # FIGURA E1: Painel 2x2 com (a) Utilização U, (b) Vazão TP, (c) MRT e MQT, (d) Descarte DP
    # --------------------------------------------------------------------------
    W, H = 560, 410
    ps = [ps_header(W, H)]
    # (a) Top-Left: Utilização U (%)
    ps.append(draw_subplot_ps(
        48, 232, 215, 145, ar_grid,
        [("Utilização U (%)", [r["U"] for r in e1_curve], c_blue, 0)],
        0.05, 0.80, 0.15, 0.0, 105.0, 21.0,
        "Taxa de chegada AR (req/ms)", "Utilização (%)", "(a) Utilização dos Servidores (U)",
        highlight_xs=e1_levels, legend_pos="br",
    ))
    # (b) Top-Right: Vazão TP (req/s)
    ps.append(draw_subplot_ps(
        322, 232, 215, 145, ar_grid,
        [("Vazão Efetiva TP (req/s)", [r["TP_s"] for r in e1_curve], c_green, 1)],
        0.05, 0.80, 0.15, 0.0, 450.0, 90.0,
        "Taxa de chegada AR (req/ms)", "Vazão TP (req/s)", "(b) Vazão do Sistema (TP)",
        highlight_xs=e1_levels, legend_pos="br",
    ))
    # (c) Bottom-Left: MRT, MQT e MPT (ms)
    ps.append(draw_subplot_ps(
        48, 42, 215, 145, ar_grid,
        [
            ("Tempo Resp. (MRT)", [r["MRT"] for r in e1_curve], c_red, 0),
            ("Tempo Fila (MQT)", [r["MQT"] for r in e1_curve], c_orange, 1),
            ("Tempo Proc. (MPT)", [r["MPT"] for r in e1_curve], c_blue, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 125.0, 25.0,
        "Taxa de chegada AR (req/ms)", "Tempo (ms)", "(c) Tempos Médios (MRT, MQT, MPT)",
        highlight_xs=e1_levels,
    ))
    # (d) Bottom-Right: Probabilidade de Descarte DP (%)
    ps.append(draw_subplot_ps(
        322, 42, 215, 145, ar_grid,
        [("Prob. Descarte DP (%)", [r["DP"] for r in e1_curve], c_red, 2)],
        0.05, 0.80, 0.15, 0.0, 60.0, 15.0,
        "Taxa de chegada AR (req/ms)", "Prob. de Descarte (%)", "(d) Probabilidade de Descarte (DP)",
        highlight_xs=e1_levels,
    ))
    ps.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps), "fig_e1_demanda", W, H)

    # --------------------------------------------------------------------------
    # FIGURA E2: Capacidade de Processamento (P_WS = 4, 8, 12) - Painel 2x2
    # --------------------------------------------------------------------------
    e2c = data["e2_curves"]
    ps = [ps_header(W, H)]
    ps.append(draw_subplot_ps(
        48, 232, 215, 145, ar_grid,
        [
            ("Config. A (P_WS=4)", [r["U"] for r in e2c[4]], c_red, 0),
            ("Config. B (P_WS=8)", [r["U"] for r in e2c[8]], c_blue, 1),
            ("Config. C (P_WS=12)", [r["U"] for r in e2c[12]], c_green, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 105.0, 21.0,
        "Taxa de chegada AR (req/ms)", "Utilização (%)", "(a) Utilização por Capacidade (U)",
        highlight_xs=[0.40], legend_pos="br",
    ))
    ps.append(draw_subplot_ps(
        322, 232, 215, 145, ar_grid,
        [
            ("Config. A (P_WS=4)", [r["TP_s"] for r in e2c[4]], c_red, 0),
            ("Config. B (P_WS=8)", [r["TP_s"] for r in e2c[8]], c_blue, 1),
            ("Config. C (P_WS=12)", [r["TP_s"] for r in e2c[12]], c_green, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 650.0, 130.0,
        "Taxa de chegada AR (req/ms)", "Vazão TP (req/s)", "(b) Vazão por Capacidade (TP)",
        highlight_xs=[0.40], legend_pos="tl",
    ))
    ps.append(draw_subplot_ps(
        48, 42, 215, 145, ar_grid,
        [
            ("Config. A (P_WS=4)", [r["MRT"] for r in e2c[4]], c_red, 0),
            ("Config. B (P_WS=8)", [r["MRT"] for r in e2c[8]], c_blue, 1),
            ("Config. C (P_WS=12)", [r["MRT"] for r in e2c[12]], c_green, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 125.0, 25.0,
        "Taxa de chegada AR (req/ms)", "MRT (ms)", "(c) Tempo Médio de Resposta (MRT)",
        highlight_xs=[0.40], legend_pos="br",
    ))
    ps.append(draw_subplot_ps(
        322, 42, 215, 145, ar_grid,
        [
            ("Config. A (P_WS=4)", [r["DP"] for r in e2c[4]], c_red, 0),
            ("Config. B (P_WS=8)", [r["DP"] for r in e2c[8]], c_blue, 1),
            ("Config. C (P_WS=12)", [r["DP"] for r in e2c[12]], c_green, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 80.0, 20.0,
        "Taxa de chegada AR (req/ms)", "Prob. de Descarte (%)", "(d) Probabilidade de Descarte (DP)",
        highlight_xs=[0.40],
    ))
    ps.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps), "fig_e2_capacidade", W, H)

    # --------------------------------------------------------------------------
    # FIGURA E3: Capacidade da Fila (C_FILA = 10, 20, 40) - Painel 1x2 (MRT e DP)
    # --------------------------------------------------------------------------
    W3, H3 = 560, 210
    e3c = data["e3_curves"]
    ps = [ps_header(W3, H3)]
    ps.append(draw_subplot_ps(
        48, 42, 215, 145, ar_grid,
        [
            ("C_FILA = 10", [r["MRT"] for r in e3c[10]], c_green, 0),
            ("C_FILA = 20", [r["MRT"] for r in e3c[20]], c_blue, 1),
            ("C_FILA = 40", [r["MRT"] for r in e3c[40]], c_red, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 125.0, 25.0,
        "Taxa de chegada AR (req/ms)", "MRT (ms)", "(a) Impacto de C_FILA no MRT",
        highlight_xs=[0.40],
    ))
    ps.append(draw_subplot_ps(
        322, 42, 215, 145, ar_grid,
        [
            ("C_FILA = 10", [r["DP"] for r in e3c[10]], c_green, 0),
            ("C_FILA = 20", [r["DP"] for r in e3c[20]], c_blue, 1),
            ("C_FILA = 40", [r["DP"] for r in e3c[40]], c_red, 2),
        ],
        0.05, 0.80, 0.15, 0.0, 60.0, 15.0,
        "Taxa de chegada AR (req/ms)", "Prob. de Descarte (%)", "(b) Impacto de C_FILA no Descarte (DP)",
        highlight_xs=[0.40],
    ))
    ps.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps), "fig_e3_fila", W3, H3)

    # --------------------------------------------------------------------------
    # FIGURA E4: Comparativo em Barras dos 3 Cenários Combinados (E4.1, E4.2, E4.3)
    # --------------------------------------------------------------------------
    W4, H4 = 560, 210
    e4_rows = data["e4_rows"]
    ps = [ps_header(W4, H4)]

    # Subplot Esquerdo: MRT e MQT (ms) nos cenários C1, C2, C3
    ox, oy, w, h = 48, 42, 215, 145
    ps.append(f"1 1 1 setrgbcolor {ox} {oy} {w} {h} rectfill")
    for yv in range(0, 76, 15):
        py = oy + (yv / 75.0) * h
        ps.append(f"0.88 0.88 0.88 setrgbcolor 0.5 setlinewidth [2 2] 0 setdash newpath {ox} {py:.1f} moveto {ox+w} {py:.1f} lineto stroke")
        ps.append(f"[] 0 setdash 0.15 0.15 0.15 setrgbcolor 8.5 F {ox-5} {py-3:.1f} moveto ({yv}) rshow")
    ps.append(f"0.1 0.1 0.1 setrgbcolor 1.0 setlinewidth {ox} {oy} {w} {h} rectstroke")

    labels_c = ["C1 (P_WS=6)", "C2 (P_WS=12)", "C3 (P_WS=16)"]
    for idx, r in enumerate(e4_rows):
        cx = ox + 38 + idx * 68
        # Barra MRT
        bh_mrt = (r["MRT"] / 75.0) * h
        ps.append(f"0.15 0.42 0.75 setrgbcolor {cx-18:.1f} {oy} 17 {bh_mrt:.1f} rectfill")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 7.5 FB {cx-9.5:.1f} {oy+bh_mrt+3:.1f} moveto ({r['MRT']:.1f}) cshow")
        # Barra MQT
        bh_mqt = (r["MQT"] / 75.0) * h
        ps.append(f"0.90 0.50 0.12 setrgbcolor {cx+1:.1f} {oy} 17 {bh_mqt:.1f} rectfill")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 7.5 FB {cx+9.5:.1f} {oy+bh_mqt+3:.1f} moveto ({r['MQT']:.1f}) cshow")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 8.2 FB {cx:.1f} {oy-13} moveto ({ps_escape(labels_c[idx])}) cshow")

    # Legenda subplot esquerdo
    ps.append(f"1 1 1 setrgbcolor {ox+95} {oy+h-32} 112 26 rectfill 0.4 0.4 0.4 setrgbcolor 0.6 setlinewidth {ox+95} {oy+h-32} 112 26 rectstroke")
    ps.append(f"0.15 0.42 0.75 setrgbcolor {ox+100} {oy+h-16} 10 7 rectfill 0.1 0.1 0.1 setrgbcolor 7.8 F {ox+114} {oy+h-15} moveto (MRT (ms)) show")
    ps.append(f"0.90 0.50 0.12 setrgbcolor {ox+100} {oy+h-27} 10 7 rectfill 0.1 0.1 0.1 setrgbcolor 7.8 F {ox+114} {oy+h-26} moveto (MQT (ms)) show")
    ps.append(f"0.05 0.05 0.05 setrgbcolor 9.5 FB {ox+w/2:.1f} {oy-27} moveto (Cenários Combinados (AR = 0,55 req/ms)) cshow")
    ps.append(f"0.05 0.05 0.05 setrgbcolor 10.0 FB {ox+w/2:.1f} {oy+h+7} moveto ((a) Tempo de Resposta (MRT) e Fila (MQT)) cshow")
    ps.append(f"gsave {ox-30} {oy+h/2:.1f} translate 90 rotate 0 0 moveto 9.5 FB (Tempo (ms)) cshow grestore")

    # Subplot Direito: Utilização U (%) e Descarte DP (%) nos cenários C1, C2, C3
    ox2 = 322
    ps.append(f"1 1 1 setrgbcolor {ox2} {oy} {w} {h} rectfill")
    for yv in range(0, 126, 25):
        py = oy + (yv / 125.0) * h
        ps.append(f"0.88 0.88 0.88 setrgbcolor 0.5 setlinewidth [2 2] 0 setdash newpath {ox2} {py:.1f} moveto {ox2+w} {py:.1f} lineto stroke")
        ps.append(f"[] 0 setdash 0.15 0.15 0.15 setrgbcolor 8.5 F {ox2-5} {py-3:.1f} moveto ({yv}) rshow")
    ps.append(f"0.1 0.1 0.1 setrgbcolor 1.0 setlinewidth {ox2} {oy} {w} {h} rectstroke")

    for idx, r in enumerate(e4_rows):
        cx = ox2 + 38 + idx * 68
        # Barra U (%)
        bh_u = (r["U"] / 125.0) * h
        ps.append(f"0.18 0.62 0.30 setrgbcolor {cx-18:.1f} {oy} 17 {bh_u:.1f} rectfill")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 7.5 FB {cx-9.5:.1f} {oy+bh_u+3:.1f} moveto ({r['U']:.1f}%) cshow")
        # Barra DP (%)
        bh_dp = (r["DP"] / 125.0) * h
        ps.append(f"0.82 0.18 0.18 setrgbcolor {cx+1:.1f} {oy} 17 {bh_dp:.1f} rectfill")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 7.5 FB {cx+9.5:.1f} {oy+bh_dp+3:.1f} moveto ({r['DP']:.1f}%) cshow")
        ps.append(f"0.1 0.1 0.1 setrgbcolor 8.2 FB {cx:.1f} {oy-13} moveto ({ps_escape(labels_c[idx])}) cshow")

    ps.append(f"1 1 1 setrgbcolor {ox2+98} {oy+h-30} 110 25 rectfill 0.4 0.4 0.4 setrgbcolor 0.6 setlinewidth {ox2+98} {oy+h-30} 110 25 rectstroke")
    ps.append(f"0.18 0.62 0.30 setrgbcolor {ox2+103} {oy+h-15} 10 7 rectfill 0.1 0.1 0.1 setrgbcolor 7.8 F {ox2+117} {oy+h-14} moveto (Utilização U (%)) show")
    ps.append(f"0.82 0.18 0.18 setrgbcolor {ox2+103} {oy+h-26} 10 7 rectfill 0.1 0.1 0.1 setrgbcolor 7.8 F {ox2+117} {oy+h-25} moveto (Descarte DP (%)) show")
    ps.append(f"0.05 0.05 0.05 setrgbcolor 9.5 FB {ox2+w/2:.1f} {oy-27} moveto (Cenários Combinados (AR = 0,55 req/ms)) cshow")
    ps.append(f"0.05 0.05 0.05 setrgbcolor 10.0 FB {ox2+w/2:.1f} {oy+h+7} moveto ((b) Utilização (U) e Prob. de Descarte (DP)) cshow")
    ps.append(f"gsave {ox2-30} {oy+h/2:.1f} translate 90 rotate 0 0 moveto 9.5 FB (Percentual (%)) cshow grestore")

    ps.append("showpage\n")
    compile_ps_to_pdf_and_png("\n".join(ps), "fig_e4_combinado", W4, H4)


if __name__ == "__main__":
    print("Executando avaliação do modelo SPN (CTMC Exata + Simulação Token Game)...")
    data = run_all_experiments()
    print(f"Experimentos concluídos! Total de cenários na tabela consolidada: {len(data['consolidated'])}")
    for row in data["consolidated"]:
        print(
            f"  {row['Experimento']:4s} | AR={row['AR']:.2f} | P_WS={row['P_WS']:2d} | C_FILA={row['C_FILA']:2d} "
            f"=> U={row['U']:6.2f}% | TP={row['TP_s']:6.2f} req/s | MQT={row['MQT']:5.2f} ms | "
            f"MPT={row['MPT']:5.2f} ms | MRT={row['MRT']:6.2f} ms | DP={row['DP']:5.2f}%"
        )
    print("Gerando diagramas e figuras científicas em PDF/PNG...")
    generate_architecture_and_spn_diagrams()
    generate_experiment_figures(data)
    print("Figuras geradas com sucesso em figures/ e artigo/figures/!")
