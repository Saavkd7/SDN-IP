"""
green_models.py
Refined Hardware Profiles based on official datasheets and experimental evidence.
Integrates Power Consumption (W) and Service Capacity (PPS).
"""

class SDNDevice:
    def get_base_power(self): raise NotImplementedError
    def get_port_power(self): raise NotImplementedError
    def get_capacity(self): raise NotImplementedError # (Service Rate in PPS)

class ZodiacFX(SDNDevice):
    """
    Zodiac FX (Low-Power / IoT Grade)
    Evidence: 120MHz CPU & 100Mbps ports
    """
    P_BASE = 15.0            # Nominal Cosumption
    P_PORT = 0.15            # Estimated for active ports
    # PHY CAPACITY (MU)
    # Baed on Realistic CPU 120MHz para OpenFlow
    MU = 100000.0            # 100 kpps ZODIAC FX
    #MU = 1000000.0 #1 Mpps  ZODIAC NG for testing other models
    # CONTROL ENERGY
    E_FLOW_MOD = 0.001455    # Watts por regla escrita
    E_PACKET_IN = 0.000775   # Watts por procesamiento de PacketIn
    def __init__(self, node_id=None): self.node_id = node_id
    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_capacity(self): return self.MU

class NEC_PF5240(SDNDevice):
    """
    NEC PF 5240 (High-Performance / ASIC Grade)
    Evidence: 131 Mpps Forwarding Rate
    """
    P_BASE = 118.33          # Valor exacto medido
    P_PORT = 0.5295          # Valor exacto medido por puerto
    
    # CAPACIDAD FÍSICA (MU)
    # Wire-speed por Hardware (ASIC Pipeline)
    MU = 131000000.0         # 131 Mpps

    # ENERGÍA DE CONTROL
    E_FLOW_MOD = 0.000029    # Muy eficiente por hardware
    E_PACKET_IN = 0.000711   # Procesamiento de control

    def __init__(self, node_id=None): self.node_id = node_id
    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_capacity(self): return self.MU

# ==============================================================================
# HERRAMIENTAS DE NORMALIZACIÓN (SISTEMA DE REFERENCIA)
# ==============================================================================
class GreenNormalizer:
    @staticmethod
    def get_max_power(max_degree):
        """El peor consumo posible: Un NEC con todos los puertos activos."""
        return NEC_PF5240.P_BASE + (max_degree * NEC_PF5240.P_PORT) 

    @staticmethod
    def get_worst_delay_threshold():
        """
        Umbral de 'Delay Inaceptable' para normalización.
        Si un paquete tarda más de 100ms (0.1s) en un switch, se considera saturado.
        """
        return 0.1
