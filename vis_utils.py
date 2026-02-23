# ==========================================
# ARCHIVO: vis_utils.py
# ==========================================
import matplotlib.pyplot as plt
import seaborn as sns
import networkx as nx
import numpy as np
import os

# Configuración estética estricta para Q1 Journals
plt.rcParams.update({
    'font.family': 'serif', 
    'font.size': 12, 
    'figure.dpi': 300,
    'axes.grid': True,
    'grid.alpha': 0.3
})

OUTPUT_DIR = "Q1_Figures"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def plot_pareto_front(df):
    """ACTO I: El Trade-off Multiobjetivo (Watts vs Delay)"""
    plt.figure(figsize=(8, 6))
    
    scatter = sns.scatterplot(
        data=df, x='Watts_Total', y='Delay_ms', 
        hue='Sigma', size='Alpha', palette='viridis', 
        sizes=(20, 150), edgecolor='black', alpha=0.8
    )
    
    plt.title('Pareto Front: Energy Consumption vs. Network Latency')
    plt.xlabel('Total Power Consumption (Watts)')
    plt.ylabel('Average Delay (ms)')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'Q1_Act1_Pareto.png'))
    plt.close()

def plot_hardware_transition(df, target_alpha=0.4):
    """ACTO II: Transición de Hardware 100% Apilada"""
    # Tolerancia flotante para buscar el Alpha
    sub_df = df[np.isclose(df['Alpha'], target_alpha)].sort_values('Sigma')
    
    if sub_df.empty:
        print(f"[WARNING] No hay datos en el CSV para Alpha={target_alpha}")
        return

    sigmas = sub_df['Sigma'].values
    nec_h = sub_df['NEC_Heros_Count'].values
    zod_h = sub_df['Zodiac_Heros_Count'].values
    nec_p = sub_df['NEC_Passive_Count'].values
    zod_p = sub_df['Zodiac_Passive_Count'].values
    
    totals = nec_h + zod_h + nec_p + zod_p
    # Evitar divisiones por cero con un pequeño epsilon si total es 0
    totals = np.where(totals == 0, 1e-9, totals) 
    
    nec_h_pct = (nec_h / totals) * 100
    zod_h_pct = (zod_h / totals) * 100
    nec_p_pct = (nec_p / totals) * 100
    zod_p_pct = (zod_p / totals) * 100
    
    plt.figure(figsize=(9, 5))
    plt.stackplot(
        sigmas, nec_h_pct, zod_h_pct, nec_p_pct, zod_p_pct,
        labels=['NEC Heros', 'Zodiac Heros', 'NEC Passive', 'Zodiac Passive'],
        colors=['#d73027', '#fc8d59', '#91bfdb', '#4575b4'], alpha=0.8
    )
    
    plt.title(f'Hardware Phase Transition under Traffic Stress ($\\alpha$={target_alpha})')
    plt.xlabel('Traffic Burst Intensity ($\\sigma$)')
    plt.ylabel('Hardware Distribution (%)')
    plt.legend(loc='upper left', bbox_to_anchor=(1.02, 1))
    plt.margins(x=0, y=0)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'Q1_Act2_HardwareTransition.png'))
    plt.close()

def plot_hero_gravity_map(df, G):
    """ACTO III: Topología y Gravedad de los Héroes"""
    plt.figure(figsize=(10, 8))
    
    try:
        pos = nx.get_node_attributes(G, 'pos')
        if not pos: raise ValueError
    except:
        pos = nx.spring_layout(G, seed=42)
        
    all_heroes = []
    for hero_list in df['WinnerSet_Names']:
        if isinstance(hero_list, list):
            all_heroes.extend(hero_list)
        
    from collections import Counter
    hero_counts = Counter(all_heroes)
    max_count = max(hero_counts.values()) if hero_counts else 1
    
    node_colors = []
    node_sizes = []
    
    for n in G.nodes():
        name = G.nodes[n].get('name', str(n))
        freq = hero_counts.get(name, 0)
        node_colors.append(freq)
        node_sizes.append(300 + (freq / max_count) * 1200)

    nx.draw_networkx_edges(G, pos, edge_color='gray', alpha=0.5)
    nodes = nx.draw_networkx_nodes(
        G, pos, node_color=node_colors, node_size=node_sizes, 
        cmap=plt.cm.Reds, edgecolors='black'
    )
    
    labels = {n: G.nodes[n].get('name', str(n)) for n in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=8, font_family='serif')
    
    plt.colorbar(nodes, label='Hero Selection Frequency (Gravity)')
    plt.title('Topological Gravity: Anchor Nodes in Hybrid Networks')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'Q1_Act3_HeroGravity.png'))
    plt.close()

def plot_stress_heatmap(df):
    """ACTO IV: Superficie de Sensibilidad (Heatmap)"""
    plt.figure(figsize=(8, 6))
    
    try:
        pivot_table = df.pivot_table(index='Alpha', columns='Sigma', values='Watts_Total', aggfunc='mean')
        
        sns.heatmap(
            pivot_table, annot=True, fmt=".0f", cmap="YlOrRd", 
            cbar_kws={'label': 'Total Power Consumption (Watts)'}, linewidths=.5
        )
        
        plt.title('System Energy Sensitivity Surface')
        plt.xlabel('Traffic Burst Intensity ($\\sigma$)')
        plt.ylabel('Routing Policy ($\\alpha$)')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, 'Q1_Act4_StressHeatmap.png'))
    except Exception as e:
        print(f"[ERROR] Fallo al generar el Heatmap. Verifica que el CSV no tenga duplicados Sigma/Alpha. Detalles: {e}")
    finally:
        plt.close()