from inspect_data import read_data, TZ
import numpy as np

for d in read_data():
    if '环境' not in d['tag']:
        continue
    mean_spectrum=d['x'].mean(axis=0)
    j=int(np.argmax(mean_spectrum))
    i,k=np.unravel_index(int(np.argmax(d['x'])),d['x'].shape)
    print(f"{d['tag']}\t平均光谱峰值DN={mean_spectrum[j]:.3f}\t峰值波长={d['w'][j]:.3f}nm"
          f"\t单帧绝对最大DN={d['x'][i,k]:.0f}\t绝对最大波长={d['w'][k]:.3f}nm"
          f"\t时间={__import__('datetime').datetime.fromtimestamp(d['t'][i],TZ).isoformat(timespec='milliseconds')}")
