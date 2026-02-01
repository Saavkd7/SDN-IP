import matplotlib.pyplot as plt
import numpy as np
import os

def plot_graph_a_tradeoff(alphas, watts_history, score_history, filename="graph_a_tradeoff.png"):
    """
    Genera la Gráfica A: Trade-off entre Energía (Watts) y Función Objetivo (Score).
    Eje Izquierdo (Verde): Consumo en Watts.
    Eje Derecho (Azul): Score de Optimización (Costo acumulado de rutas).
    """
    fig, ax1 = plt.subplots(figsize=(10, 6))

    # --- EJE Y 1: POTENCIA (WATTS) ---
    color_watts = 'tab:green'
    ax1.set_xlabel('Alpha (0 = Prioridad Velocidad, 1 = Prioridad Energía)', fontsize=12)
    ax1.set_ylabel('Total Network Power (Watts)', color=color_watts, fontsize=12, fontweight='bold')
    # Graficamos con marcadores sólidos para ver los puntos exactos
    ax1.plot(alphas, watts_history, color=color_watts, marker='o', linewidth=2, label='Power (W)')
    ax1.tick_params(axis='y', labelcolor=color_watts)
    ax1.grid(True, linestyle='--', alpha=0.5)

    # --- EJE Y 2: SCORE (METRIC) ---
    ax2 = ax1.twinx()  # Instancia un segundo eje que comparte el mismo eje X
    color_score = 'tab:blue'
    ax2.set_ylabel('Optimization Cost Metric (Lower is Better)', color=color_score, fontsize=12, fontweight='bold')
    # Usamos línea punteada para diferenciar
    ax2.plot(alphas, score_history, color=color_score, marker='x', linestyle='--', linewidth=2, label='Path Cost Metric')
    ax2.tick_params(axis='y', labelcolor=color_score)

    # TÍTULO Y GUARDADO
    plt.title('GRAPH A: Energy vs. Performance Trade-off Analysis', fontsize=14)
    fig.tight_layout()  # Ajusta para que no se corten las etiquetas
    
    if os.path.exists(filename):
        os.remove(filename)
    plt.savefig(filename, dpi=300) # 300 DPI es calidad de impresión/tesis
    print(f"[GRAPHIC] Graph A saved successfully as '{filename}'")
    plt.close()


def plot_graph_b_savings(baseline_watts, green_watts, filename="graph_b_savings.png"):
    """
    Genera la Gráfica B: Comparativa de Impacto (Baseline vs Green).
    Gráfico de Barras con anotaciones de porcentaje.
    """
    labels = ['Standard Approach\n(All-NEC)', 'Green MCS Approach\n(Hybrid)']
    values = [baseline_watts, green_watts]
    colors = ['#d62728', '#2ca02c'] # Rojo (Malo/Alto) y Verde (Bueno/Bajo)

    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Crear las barras
    bars = ax.bar(labels, values, color=colors, width=0.5)

    # Títulos y Etiquetas
    ax.set_ylabel('Power Consumption (Watts)', fontsize=12)
    ax.set_title('GRAPH B: Energy Efficiency Impact Analysis', fontsize=14)
    
    # Calcular ahorro
    saved = baseline_watts - green_watts
    percent = (saved / baseline_watts) * 100

    # --- ANOTACIONES AUTOMÁTICAS ENCIMA DE LAS BARRAS ---
    # Barra 1 (Standard)
    ax.text(bars[0].get_x() + bars[0].get_width()/2., baseline_watts + 10,
            f'{baseline_watts:.1f} W', 
            ha='center', va='bottom', fontsize=11, fontweight='bold')

    # Barra 2 (Green)
    ax.text(bars[1].get_x() + bars[1].get_width()/2., green_watts + 10,
            f'{green_watts:.1f} W', 
            ha='center', va='bottom', fontsize=11, fontweight='bold')

    # Flecha y Texto de Ahorro en el centro
    mid_point = (baseline_watts + green_watts) / 2
    ax.annotate(f'SAVING\n-{percent:.1f}%', 
                xy=(0.5, mid_point), xycoords='axes fraction', # Posición relativa
                ha='center', fontsize=12, fontweight='bold', color='green',
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="green", lw=2))

    # Limite Y un poco más alto para que quepa el texto
    ax.set_ylim(0, max(values) * 1.15)
    ax.grid(axis='y', linestyle='--', alpha=0.5)

    if os.path.exists(filename):
        os.remove(filename)
    plt.savefig(filename, dpi=300)
    print(f"[GRAPHIC] Graph B saved successfully as '{filename}'")
    plt.close()
