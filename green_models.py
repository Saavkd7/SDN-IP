class SDNDevice:
    def get_base_power(self): raise NotImplementedError
    def get_port_power(self): raise NotImplementedError
    def get_capacity(self): raise NotImplementedError
    def get_control_energy(self): raise NotImplementedError

class ZodiacFX(SDNDevice):
    P_BASE = 15.0
    P_PORT = 0.15
    MU = 100000.0
    E_FLOW_MOD = 0.001455
    E_PACKET_IN = 0.000775

    def __init__(self, node_id=None): self.node_id = node_id
    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_capacity(self): return self.MU
    def get_control_energy(self): return (self.E_FLOW_MOD, self.E_PACKET_IN)

class NEC_PF5240(SDNDevice):
    P_BASE = 118.33
    P_PORT = 0.5295
    MU = 131000000.0
    E_FLOW_MOD = 0.000029
    E_PACKET_IN = 0.000711

    def __init__(self, node_id=None): self.node_id = node_id
    def get_base_power(self): return self.P_BASE
    def get_port_power(self): return self.P_PORT
    def get_capacity(self): return self.MU
    def get_control_energy(self): return (self.E_FLOW_MOD, self.E_PACKET_IN)

# ==============================================================================
# CENTRALIZED HARDWARE FACTORY (The "One Place" to change everything)
# ==============================================================================
class HardwareFactory:
    """
    Fábrica inteligente: Decide dinámicamente el perfil de hardware 
    en función de la carga de tráfico ingresada.
    """
    @classmethod
    def get_device(cls, traffic_load, node_id=None):
        # 1. Forzamos el tipo a float para evitar bugs de NumPy 2.x
        load = float(traffic_load) 
        threshold = (ZodiacFX.MU * 0.95) - 1e-7
        
        # 2. Imprimimos para depurar
        print(f"Load: {load:.10f} | Umbral: {threshold:.10f}")
        
        # 3. Evaluamos con la variable correcta
        if load < threshold:
            return ZodiacFX(node_id)
        return NEC_PF5240(node_id)

class GreenNormalizer:
    @staticmethod
    def get_max_power(max_degree):
        """El peor consumo posible para la normalización siempre será el NEC."""
        return NEC_PF5240.P_BASE + (max_degree * NEC_PF5240.P_PORT) 

    @staticmethod
    def get_worst_delay_threshold():
        return 0.1
