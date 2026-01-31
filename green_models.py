"""
green_models.py
Based on Table VII: Switch Power Consumption Parameters.
"""

class SDNDevice:
    def get_base_power(self): return 0.0
    def get_port_power(self): return 0.0 # Watts per port
    def get_rule_cost(self, n=1): return 0.0
    def get_packet_in_cost(self, n=1): return 0.0

class ZodiacFX(SDNDevice):
    """
    Zodiac FX (Light Hardware - Edge)
    """
    P_BASE = 15.0          #
    P_PORT = 0.15          #
    E_FLOW_MOD = 0.001455  # Watts (1455.13 uW)
    E_PACKET_IN = 0.000775 # Watts (775.53 uW)

    def __init__(self, node_id): self.node_id = node_id

    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_rule_cost(self, n=1): return n * self.E_FLOW_MOD
    def get_packet_in_cost(self, n=1): return n * self.E_PACKET_IN

class NEC_PF5240(SDNDevice):
    """
    NEC PF 5240 (Heavy Hardware - Core/Legacy)
    """
    P_BASE = 118.33        #
    P_PORT = 0.52          #
    E_FLOW_MOD = 0.000029  # Watts (29.25 uW)
    E_PACKET_IN = 0.000711 # Watts (711.30 uW)

    def __init__(self, node_id): self.node_id = node_id

    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_rule_cost(self, n=1): return n * self.E_FLOW_MOD
    def get_packet_in_cost(self, n=1): return n * self.E_PACKET_IN
    
    @staticmethod
    def get_max_theoretical_watts(max_degree):
        """
        Retorna el consumo máximo teórico para normalización.
        Asume un NEC a full carga de puertos.
        """
        return NEC_PF5240.P_BASE + (max_degree * NEC_PF5240.P_PORT)