import matplotlib.pyplot as plt
import numpy as np
import networkx as nx
import os
import math  # <--- CRÍTICO PARA FÍSICA
from green_models import NEC_PF5240, ZodiacFX

# Directorio de salida
OUTPUT_DIR = "img_results"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def save_plot(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[VIS] Saved graphic to: {path}")

# ==========================================
# MOTOR DE FÍSICA (Scientific Calculation)
# ==========================================
def haversine_distance(coord1, coord2):
    """Calcula distancia en Km entre dos puntos (lon, lat)"""
    R = 6371  # Radio Tierra km
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_real_path_latency(G, path):
    """
    Calcula la latencia acumulada de un camino (lista de nodos)
    usando la velocidad de la luz en fibra (200,000 km/s).
    """
    total_ms = 0.0
    SPEED_FIBER = 200.0 # km/ms
    
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        
        # 1. Intentar usar peso pre-calculado si es confiable
        # edge_w = G[u][v].get('weight', 0)
        # if edge_w > 0: 
        #     total_ms += edge_w
        #     continue
            
        # 2. Si no, calcular desde coordenadas (PLAN B ROBUSTO)
        try:
            # SNDLib a veces guarda en 'pos' (tupla) o atributos x, y
            u_node = G.nodes[u]
            v_node = G.nodes[v]
            
            # Extracción robusta de coordenadas
            c1 = u_node.get('pos')
            if not c1: c1 = (u_node.get('x', 0), u_node.get('y', 0))
            
            c2 = v_node.get('pos')
            if not c2: c2 = (v_node.get('x', 0), v_node.get('y', 0))
            
            dist = haversine_distance(c1, c2)
            delay = (dist / SPEED_FIBER) + 0.05 # +0.05ms switching overhead
            total_ms += delay
        except:
            total_ms += 1.0 # Fallback 1ms si falla la física
            
    return total_ms

# --- ESTADÍSTICAS GLOBALES ---
# --- ESTADÍSTICAS GLOBALES ---
def calculate_real_physics(G, h, winner_set, failover_map, node_traffic_pps, force_type=None):
    """
    Retorna (Watts Reales, Latencia Promedio ms).
    Admite 'force_type' para escenarios de Benchmark (ALL_NEC, ALL_ZODIAC).
    Implementa política 'Green-First' por defecto.
    """
    total_watts = 0.0
    ZODIAC_CAP = ZodiacFX.MU * 0.95
    SATURATION_PENALTY_MS = 2000.0 # 2 segundos si colapsa (para gráfica)
    
    # Diccionario para guardar qué capacidad tiene cada nodo según el escenario
    node_caps = {}

    # 1. Energía Real y Configuración de Hardware
    for n in G.nodes():
        lam = node_traffic_pps.get(n, 0.0)
        
        # --- LÓGICA DE SELECCIÓN DE HARDWARE ---
        if force_type == 'ALL_NEC':
            # Escenario Base: Todo Legacy
            hw_base = NEC_PF5240.P_BASE
            hw_port = NEC_PF5240.P_PORT
            mu = NEC_PF5240.MU
            
        elif force_type == 'ALL_ZODIAC':
            # Escenario Riesgoso: Todo Green (aunque sature)
            hw_base = ZodiacFX.P_BASE
            hw_port = ZodiacFX.P_PORT
            mu = ZodiacFX.MU
            
        else:
            # Escenario Green-MCS (Green-First Policy)
            # CORRECCIÓN: Solo los miembros del 'winner_set' tienen permiso de ser Green.
            # El resto de la red (Backbone) se mantiene como NEC por seguridad.
            
            if n in winner_set and lam < ZODIAC_CAP:
                hw_base = ZodiacFX.P_BASE
                hw_port = ZodiacFX.P_PORT
                mu = ZodiacFX.MU
            else:
                # Si no es Héroe, o si es Héroe pero está saturado -> NEC
                hw_base = NEC_PF5240.P_BASE
                hw_port = NEC_PF5240.P_PORT
                mu = NEC_PF5240.MU
        
        # Guardamos capacidad para cálculo de latencia
        node_caps[n] = mu
        # Sumamos Watts
        total_watts += hw_base + (G.degree(n) * hw_port)

    # 2. Latencia Real (ms) con Física y Colas
    total_latency = 0.0
    count = 0
    
    for (u, v), hero in failover_map.items():
        affected = h.get((u, v), [])
        if not affected: continue
        
        # Recuperamos la capacidad del héroe asignado en este escenario
        mu = node_caps.get(hero, NEC_PF5240.MU)
        lam = node_traffic_pps.get(hero, 0.0)
        
        # M/M/1 Queue Delay con detección de Saturación
        if lam >= mu * 0.99:
            q_ms = SATURATION_PENALTY_MS # ¡Buffer Lleno!
        else:
            q_ms = (1.0 / (mu - lam)) * 1000.0 # ms
        
        try:
            # Caminos físicos
            path_tun = nx.shortest_path(G, u, hero, weight='weight')
            lat_tun = get_real_path_latency(G, path_tun)
            
            lat_rep_accum = 0
            for d in affected:
                path_rep = nx.shortest_path(G, hero, d, weight='weight')
                lat_rep_accum += get_real_path_latency(G, path_rep)
            
            avg_rep = lat_rep_accum / len(affected)
            
            total_latency += (lat_tun + avg_rep + q_ms)
            count += 1
        except:
            pass

    avg_ms = (total_latency / count) if count > 0 else 0.0
    return total_watts, avg_ms

# ==========================================
# GRÁFICAS
# ==========================================

def plot_alpha_sensitivity(G, h, candidate_table, valid_sets, node_traffic_pps, solver_func, sigma=0):
    print(f"\n[VIS] 1. Generating Alpha Sensitivity (Sigma={sigma})...")
    alphas = np.linspace(0.0, 1.0, 11)
    k_vals = []
    labels = []
    Z_CAP = ZodiacFX.MU * 0.95

    for a in alphas:
        w_set, _, _ = solver_func(G, h, candidate_table, valid_sets, a, node_traffic_pps)
        k_vals.append(len(w_set) if w_set else 0)
        
        if w_set:
            l = []
            for n in sorted(list(w_set)):
                tag = "(Z)" if node_traffic_pps.get(n,0) < Z_CAP else "(N)"
                l.append(f"{n}{tag}")
            labels.append(str(l).replace("'",""))
        else:
            labels.append("[]")

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.step(alphas, k_vals, where='mid', color='green', linewidth=2)
    
    last = ""
    for i, txt in enumerate(labels):
        if txt != last:
            ax.annotate(f"a={alphas[i]:.1f}\n{txt}", xy=(alphas[i], k_vals[i]), 
                        xytext=(0, 20 + (i%2)*20), textcoords='offset points',
                        bbox=dict(boxstyle="round", fc="white", alpha=0.9), fontsize=8, ha='center',
                        arrowprops=dict(arrowstyle="->"))
            last = txt
            
    # --- CAMBIO AQUÍ: Título y nombre de archivo dinámicos ---
    ax.set_title(f"1. Sensitivity Analysis: Hardware Roles (Sigma={int(sigma)}B)", fontsize=14)
    ax.set_xlabel("Alpha")
    ax.set_ylabel("Set Size (K)")
    ax.grid(True, linestyle=':')
    save_plot(f"1_alpha_sensitivity_sigma_{int(sigma)}.png")

def analyze_tradeoffs(G, h, candidate_table, valid_sets, node_traffic_pps, solver_func, sigma=0):
    print(f"\n[VIS] 2. Generating Trade-off Analysis (Real Physics, Sigma={sigma})...")
    alphas = np.linspace(0.0, 1.0, 11)
    watts_list = []
    delay_list = []
    
    base_watts = sum([NEC_PF5240.P_BASE + (G.degree(n)*NEC_PF5240.P_PORT) for n in G.nodes()])
    
    for a in alphas:
        w_set, _, _ = solver_func(G, h, candidate_table, valid_sets, a, node_traffic_pps)
        
        temp_fail = {}
        for k_fail, v_cands in candidate_table.items():
            valid = [x for x in v_cands if x in w_set]
            if valid: temp_fail[k_fail] = valid[0] 
            
        real_w, real_ms = calculate_real_physics(G, h, w_set, temp_fail, node_traffic_pps)
        watts_list.append(real_w)
        delay_list.append(real_ms)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10), sharex=True)
    
    # Watts
    ax1.plot(alphas, [base_watts]*11, 'r--', label='Legacy (All-NEC)')
    ax1.plot(alphas, watts_list, 'g-o', label='Green-MCS', linewidth=2)
    ax1.fill_between(alphas, watts_list, base_watts, color='green', alpha=0.1)
    ax1.set_ylabel("Power Consumption (W)")
    ax1.set_title(f"Energy Efficiency Trade-off (Sigma={int(sigma)}B)", fontsize=14) # <-- CAMBIO
    ax1.legend()
    ax1.grid(True, alpha=0.5)
    
    # Delay
    ax2.plot(alphas, delay_list, 'b-s', linewidth=2)
    ax2.set_ylabel("Avg Recovery Latency (ms)")
    ax2.set_xlabel("Alpha Preference")
    ax2.set_title("QoS Impact (Physics-based)", fontsize=14)
    ax2.grid(True, alpha=0.5)
    
    # --- CAMBIO AQUÍ: Nombre de archivo dinámico ---
    save_plot(f"2_tradeoff_analysis_sigma_{int(sigma)}.png")

def analyze_three_metrics(G, h, candidate_table, valid_sets, node_traffic_pps, solver_func, weight_func, score_func):
    print("\n[VIS] 3. Generating Multi-Metric Analysis...")
    alphas = np.linspace(0.0, 1.0, 11)
    sav_pct = []
    lat_ms = []
    obj_scores = []
    
    base_watts = sum([NEC_PF5240.P_BASE + (G.degree(n)*NEC_PF5240.P_PORT) for n in G.nodes()])

    for a in alphas:
        w_set, _, w_score = solver_func(G, h, candidate_table, valid_sets, a, node_traffic_pps)
        
        temp_fail = {}
        for k, v in candidate_table.items():
            inter = [x for x in v if x in w_set]
            if inter: temp_fail[k] = inter[0]
            
        real_w, real_ms = calculate_real_physics(G, h, w_set, temp_fail, node_traffic_pps)
        
        sav_pct.append(((base_watts - real_w)/base_watts)*100)
        lat_ms.append(real_ms)
        obj_scores.append(w_score)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
    ax1.plot(alphas, sav_pct, 'g-o'); ax1.set_ylabel("% Savings"); ax1.grid(True)
    ax2.plot(alphas, lat_ms, 'r-s'); ax2.set_ylabel("Latency (ms)"); ax2.grid(True)
    ax3.plot(alphas, obj_scores, 'b-^'); ax3.set_ylabel("Objective Score"); ax3.grid(True)
    ax3.set_xlabel("Alpha")
    
    save_plot("3_multimetric_analysis.png")

def plot_hero_load_distribution(failover_map, winner_set):
    print("\n[VIS] 4. Generating Load Distribution...")
    load = {h:0 for h in winner_set}
    for _, h in failover_map.items():
        if h in load: load[h] += 1
        
    names = [str(x) for x in load.keys()]
    vals = list(load.values())
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(names, vals, color='skyblue', edgecolor='black')
    ax.bar_label(bars)
    ax.set_title("Control Plane Load Balancing")
    ax.set_ylabel("Protected Links")
    save_plot("4_hero_load_distribution.png")

def plot_recovery_delay_cdf(G, h, failover_map, score_func):
    print("\n[VIS] 5. Generating Delay CDF (Real Physics)...")
    delays = []
    
    for (u,v), hero in failover_map.items():
        aff = h.get((u,v), [])
        if not aff: continue
        try:
            # Usamos get_real_path_latency para obtener ms reales
            path_1 = nx.shortest_path(G, u, hero, weight='weight')
            ms_1 = get_real_path_latency(G, path_1)
            
            ms_2_accum = 0
            for d in aff: 
                path_2 = nx.shortest_path(G, hero, d, weight='weight')
                ms_2_accum += get_real_path_latency(G, path_2)
            
            delays.append(ms_1 + (ms_2_accum/len(aff)))
        except: pass
        
    if not delays: return
    
    srt = np.sort(delays)
    p = 1. * np.arange(len(srt)) / (len(srt) - 1)
    
    fig, ax = plt.subplots(figsize=(10,6))
    ax.plot(srt, p, 'r-', linewidth=3)
    ax.set_title("CDF of Recovery Latency (Physics: Fiber Speed)")
    ax.set_xlabel("Latency (ms)") # AHORA SÍ SON MS
    ax.set_ylabel("Probability")
    ax.grid(True)
    
    # SLA
    if len(p) > 0:
        idx = (np.abs(p - 0.9)).argmin()
        val = srt[idx]
        ax.axvline(val, color='k', linestyle=':')
        ax.text(val, 0.5, f" 90% < {val:.1f}ms", rotation=90)
        
    save_plot("5_recovery_delay_cdf.png")

def plot_k_size_impact(G, h, candidate_table, valid_sets, node_traffic_pps, solver_func, alpha=1.0):
    print("\n[VIS] 6. Generating K-Size Impact...")
    best_per_k = {}
    
    for s in valid_sets:
        k = len(s)
        _, _, score = solver_func(G, h, candidate_table, [s], alpha, node_traffic_pps)
        
        # Watts reales para la gráfica
        z_cap = ZodiacFX.MU * 0.95
        real_watts = 0
        for n in G.nodes():
            hw_b, hw_p = (NEC_PF5240.P_BASE, NEC_PF5240.P_PORT)
            if n in s and node_traffic_pps.get(n,0) < z_cap:
                hw_b, hw_p = (ZodiacFX.P_BASE, ZodiacFX.P_PORT)
            real_watts += hw_b + (G.degree(n)*hw_p)

        if k not in best_per_k or score < best_per_k[k]['score']:
            best_per_k[k] = {'watts': real_watts, 'score': score}

    ks = sorted(best_per_k.keys())
    ws = [best_per_k[k]['watts'] for k in ks]
    sc = [best_per_k[k]['score'] for k in ks]
    
    fig, ax1 = plt.subplots(figsize=(10,6))
    ax1.bar(ks, ws, color='green', alpha=0.6)
    ax1.set_ylabel("Total Power (W)", color='green')
    ax1.set_xlabel("Set Size (K)")
    
    ax2 = ax1.twinx()
    ax2.plot(ks, sc, 'b-o', linewidth=2)
    ax2.set_ylabel("Optimization Score", color='blue')
    
    ax1.set_title(f"Size vs Efficiency (Alpha={alpha})")
    save_plot("6_k_size_impact.png")

# ==========================================
# 7. NUEVA GRÁFICA: EXTREME SCENARIOS
# ==========================================
# --- MODIFICACIÓN EN vis_utils.py ---

def plot_extreme_scenarios_comparison(G, h, winner_set, failover_map, node_traffic_pps, precalculated_green_watts=None):
    """
    Compara 3 Escenarios:
    1. All-NEC (Máximo Rendimiento, Máximo Consumo)
    2. Green-MCS (Híbrido Óptimo)
    3. All-Zodiac (Mínimo Consumo, Riesgo de Colapso)
    
    precalculated_green_watts: Valor exacto de potencia calculado por el optimizador (para consistencia).
    """
    print("\n[VIS] 7. Generating Extreme Scenarios Benchmark...")
    
    scenarios = ['All-NEC (Legacy)', 'Green-MCS (Ours)', 'All-Zodiac (Risky)']
    watts_vals = []
    delay_vals = []
    
    # 1. Calcular All-NEC
    w1, d1 = calculate_real_physics(G, h, winner_set, failover_map, node_traffic_pps, force_type='ALL_NEC')
    watts_vals.append(w1)
    delay_vals.append(d1)
    
    # 2. Calcular Green-MCS
    # USAR EL VALOR PRE-CALCULADO SI EXISTE (SOLUCIÓN AL BUG)
    if precalculated_green_watts is not None:
        w2 = precalculated_green_watts
        # Recalculamos solo el delay para asegurar coherencia física
        _, d2 = calculate_real_physics(G, h, winner_set, failover_map, node_traffic_pps, force_type=None)
    else:
        w2, d2 = calculate_real_physics(G, h, winner_set, failover_map, node_traffic_pps, force_type=None)
        
    watts_vals.append(w2)
    delay_vals.append(d2)
    
    # 3. Calcular All-Zodiac
    w3, d3 = calculate_real_physics(G, h, winner_set, failover_map, node_traffic_pps, force_type='ALL_ZODIAC')
    watts_vals.append(w3)
    delay_vals.append(d3)

    # --- PLOTTING ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Gráfica de Potencia
    colors = ['#e74c3c', '#2ecc71', '#f1c40f'] # Rojo, Verde, Amarillo
    bars1 = ax1.bar(scenarios, watts_vals, color=colors, alpha=0.8, edgecolor='black')
    ax1.set_ylabel('Total Power Consumption (Watts)', fontsize=12)
    ax1.set_title('Energy Benchmark', fontsize=14)
    ax1.grid(axis='y', linestyle='--', alpha=0.5)
    ax1.bar_label(bars1, fmt='%.0f W')
    
    # Gráfica de Latencia
    bars2 = ax2.bar(scenarios, delay_vals, color=colors, alpha=0.8, edgecolor='black')
    ax2.set_ylabel('Avg Recovery Latency (ms)', fontsize=12)
    ax2.set_title('QoS Benchmark (Latency)', fontsize=14)
    ax2.grid(axis='y', linestyle='--', alpha=0.5)
    
    # Anotación de Saturación
    if delay_vals[2] >= 1000: 
        ax2.text(2, delay_vals[2], "SATURATION\n(Queue Full)", ha='center', va='bottom', 
                 color='red', fontweight='bold')
    else:
        ax2.bar_label(bars2, fmt='%.1f ms')

    plt.suptitle("Why Green-MCS? The Sweet Spot Analysis", fontsize=16)
    plt.tight_layout()
    save_plot("7_extreme_scenarios.png")

# ==========================================
# 8. NUEVA GRÁFICA: STOCHASTIC VARIANCE (PROF. MAURO)
# ==========================================
def plot_stochastic_variance_analysis(sigmas, watts_vals, delay_vals):
    print("\n[VIS] 8. Generating Stochastic Variance Analysis (Packet Size)...")
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    labels = [f"Sigma={int(s)}B" for s in sigmas]
    # Colores: Azul (Estable), Morado (Varianza Media), Rojo (Varianza Alta/IoT Burst)
    colors = ['#3498db', '#9b59b6', '#e74c3c'] 
    
    # --- Gráfica de Potencia (Watts) ---
    bars1 = ax1.bar(labels, watts_vals, color=colors, alpha=0.8, edgecolor='black')
    ax1.set_ylabel('Total Power Consumption (Watts)', fontsize=12)
    ax1.set_title('Energy Impact of Packet Variance', fontsize=14)
    ax1.grid(axis='y', linestyle='--', alpha=0.5)
    ax1.bar_label(bars1, fmt='%.0f W', padding=3)
    
    # --- Gráfica de Latencia (QoS) ---
    bars2 = ax2.bar(labels, delay_vals, color=colors, alpha=0.8, edgecolor='black')
    ax2.set_ylabel('Avg Recovery Latency (ms)', fontsize=12)
    ax2.set_title('QoS Resilience under Burst Traffic', fontsize=14)
    ax2.grid(axis='y', linestyle='--', alpha=0.5)
    
    # Manejar saturación visualmente si ocurre
    for i, delay in enumerate(delay_vals):
        if delay >= 1000:
            ax2.text(i, delay, "SATURATION\n(Queue Full)", ha='center', va='bottom', color='red', fontweight='bold')
        else:
            ax2.text(i, delay + (max(delay_vals)*0.01), f"{delay:.1f} ms", ha='center', va='bottom')

    plt.suptitle("Stochastic Packet Size Sensitivity Analysis (Mean=800B)", fontsize=16, fontweight='bold')
    plt.tight_layout()
    save_plot("8_stochastic_variance_analysis.png")
