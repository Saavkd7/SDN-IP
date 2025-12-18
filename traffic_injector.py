import time
from mininet.net import Mininet
CITY_ORDER = ['ATLA', 'CHIN', 'DNVR', 'HSTN', 'IPLS', 
              'KSCY', 'LOSA', 'NYCM', 'SNVA', 'STTL', 'WASH']
#===========================================================================================================================
def parse_traffic_matrix(path,scaling_factor):
    flows=[]
    print(f"Parsing Traffic Matrix:{path}")
    with open (path, 'r') as file:
        lines=file.readlines()
        for row_idx,line in enumerate(lines):
            if row_idx >=len(CITY_ORDER):
                break
            values=line.strip().split(',')
            for col_idx, val in enumerate(values):
                if col_idx >= len(CITY_ORDER): break
                try:
                    raw_val=float(val)
                    #filter loops a zero traffic
                    if row_idx==col_idx or raw_val==0:
                        continue
                    bw=(raw_val*1000)*scaling_factor
                    if bw >0.1:
                        src=CITY_ORDER[row_idx]
                        dst=CITY_ORDER[col_idx]
                        flows.append((src,dst,bw))
                except ValueError:
                    continue
    print(f"Parsed {len(flows)} flows from matrix")
    return flows
#==========================================================================================================================
def inject_traffic(net,flows,duration=30):
    #INjects UPD TRAFFIC INTO THE MININET NETWORK USING IPERF
    print(f"Starting Traffic INjectio (Duration: {duration}s)")
    for city in CITY_ORDER:
        host=net.get(f"h_{city}")
        host.cmd('kill all -9 iperf') #CleanUP Previous RUNs
        host.cmd('iperf -s -u &')
    time.sleep(2) # allow servers

    print("LAUNCHING") 
    active_flows=0
    for src_n , dst_n, bw in flows:
        try:
            src_h= net.get(f'h_{src_n}')
            dst_h=net.get(f'h_{dst_n}')
            dst_ip=dst_h.IP()
            #IPERF IN BACKGROUND
            # -u : udp
            #-b: bandwidth
            #-t: duration
            cmd=f'iperf -c {dst_ip} -u -b {bw:.2f}M -t {duration}&'
            src_h.cmd(cmd)
            active_flows += 1
        except Exception as e:
            print(f"Error starting flow {src_h} to {dst_h}: {e}")
    
    print(f"ALl {active_flows} flows running. Waiting for completiion")
    #wait for the experiment to finisht
    time.sleep(duration +2)
    print("expriment complete. Stopping servers")
    for city in CITY_ORDER:
        net.get(f'h_{city}').cmd('killall -9 iperf') #=====================================================================================================================               
