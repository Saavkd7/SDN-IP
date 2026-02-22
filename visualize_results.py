import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Configuración estética para Paper Q1 (Fuente legible, alta resolución)
plt.rcParams.update({'font.size': 12, 'figure.dpi': 150})
sns.set_theme(style="whitegrid")

def plot_scientific_results(csv_file):
    df = pd.read_csv(csv_file)
    
    # 1. EL FRENTE DE PARETO (El corazón del paper)
    # Muestra el compromiso entre Energía y Latencia para cada Sigma
    plt.figure(figsize=(10, 6))
    palette = sns.color_palette("viridis", as_cmap=False, n_colors=df['Sigma'].nunique())
    
    sns.lineplot(data=df, x='Watts_Total', y='Delay_ms', hue='Sigma', 
                 style='Sigma', markers=True, dashes=False, palette=palette)
    
    # Añadimos etiquetas para los valores de Alpha en los puntos
    for i in range(df.shape[0]):
        plt.text(df.Watts_Total[i]+2, df.Delay_ms[i]+0.2, f"α={df.Alpha[i]}", fontsize=9)

    plt.title("Pareto Frontier: Energy Consumption vs. Recovery Delay")
    plt.xlabel("Total Network Power (Watts)")
    plt.ylabel("Avg. Response Delay (ms)")
    plt.legend(title="Traffic Scale (Sigma)", bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig("pareto_frontier.png")
    plt.show()

    # 2. EVOLUCIÓN DEL HARDWARE (El impacto del Burst/Sigma)
    # Muestra cómo el sistema se ve obligado a escalar a NEC
    plt.figure(figsize=(10, 6))
    df['Total_NEC'] = df['NEC_Heros'] + df['NEC_Passive']
    
    # Filtramos para un Alpha balanceado (0.5) para ver el efecto del tráfico puro
    df_hw = df[df['Alpha'] == 0.5]
    
    sns.barplot(data=df_hw, x='Sigma', y='Total_NEC', color='seagreen')
    plt.title("Hardware Scalability: NEC Deployment vs. Traffic Load")
    plt.xlabel("Traffic Scale Factor (Sigma)")
    plt.ylabel("Number of NEC Switches Deployed")
    plt.tight_layout()
    plt.savefig("hardware_evolution.png")
    plt.show()

    # 3. SENSIBILIDAD DE ALPHA (El control del Orquestador)
    # Muestra cuánto ahorras realmente al mover la perilla de Alpha
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x='Alpha', y='Watts_Total', palette="light:g_r")
    plt.title("Energy Sensitivity: Impact of Alpha on Power Savings")
    plt.xlabel("Alpha (Policy Weight: 0=Perf, 1=Eco)")
    plt.ylabel("Total Network Power (Watts)")
    plt.tight_layout()
    plt.savefig("alpha_sensitivity.png")
    plt.show()

if __name__ == '__main__':
    plot_scientific_results("simulation_results.csv")
