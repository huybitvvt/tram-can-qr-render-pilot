"""Train/export the original LED glyph verifier; never consumes field images.

Development tool only. Requires PyTorch and ONNX in a separate training
environment; neither package is added to the Windows application's runtime.
The output remains separate until its model card and regressions are reviewed.
"""
import argparse
import json,random,time
from pathlib import Path
import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset,DataLoader

from tramcan_rapidocr.leading_led import normalize_glyph as normalize
PATTERNS=['abcdef','bc','abdeg','abcdg','bcfg','acdfg','acdefg','abc','abcdefg','abcdfg']
INVALID=[''.join(c for i,c in enumerate('abcdefg') if n&(1<<i)) for n in range(1,128)]
INVALID=[p for p in INVALID if p not in PATTERNS and p!='g']


class GlyphNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.network=nn.Sequential(
            nn.Conv2d(1,12,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
            nn.Conv2d(12,24,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
            nn.Conv2d(24,32,3,padding=1),nn.ReLU(),nn.Flatten(),
            nn.Linear(32*12*8,64),nn.ReLU(),nn.Linear(64,11))
    def forward(self,x):return self.network(x)


def render(label,rng):
    pattern=PATTERNS[label] if label<10 else rng.choice(INVALID)
    h=64;w=rng.randint(18,43);pad=8
    image=np.zeros((h+pad*2,w+pad*2),np.uint8)
    l=.14*w;r=.86*w;t=5;m=31;b=57;thick=rng.randint(3,8)
    coords={'a':((l+2,t),(r-2,t)),'b':((r,t+3),(r,m-3)),'c':((r,m+3),(r,b-3)),
            'd':((l+2,b),(r-2,b)),'e':((l,m+3),(l,b-3)),'f':((l,t+3),(l,m-3)),
            'g':((l+2,m),(r-2,m))}
    for s in pattern:
        p,q=coords[s]
        if s in 'bcef' and rng.random()<.5:p=(p[0],p[1]-2);q=(q[0],q[1]+2)
        cv2.line(image,(pad+round(p[0]),pad+round(p[1])),(pad+round(q[0]),pad+round(q[1])),255,thick,cv2.LINE_AA)
    if label in (1,7) and rng.random()<.7:
        # Some LED heads have a connected right stem and a short luminous foot.
        cv2.line(image,(pad+round(r),pad+t+3),(pad+round(r),pad+b-2),255,thick,cv2.LINE_AA)
        if rng.random()<.65:
            foot=rng.randint(1,max(2,round(w*.30)))
            cv2.line(image,(pad+round(r)-foot,pad+b-2),(pad+round(r)+1,pad+b-2),255,thick,cv2.LINE_AA)
    slope=rng.uniform(-.35,.35);offset=round(abs(slope)*image.shape[0])
    image=cv2.warpAffine(image,np.float32([[1,slope,offset],[0,1,0]]),(image.shape[1]+offset*2,image.shape[0]))
    angle=rng.uniform(-7,7);matrix=cv2.getRotationMatrix2D((image.shape[1]/2,image.shape[0]/2),angle,1)
    image=cv2.warpAffine(image,matrix,(image.shape[1],image.shape[0]))
    dh=rng.randint(18,65);dw=max(4,round(image.shape[1]*dh/image.shape[0]*rng.uniform(.8,1.2)))
    image=cv2.resize(image,(dw,dh),interpolation=cv2.INTER_AREA)
    if rng.random()<.4:image=cv2.GaussianBlur(image,(3,3),rng.uniform(.2,.7))
    threshold=rng.randint(65,160);mask=image>threshold
    return normalize(mask)


class Synth(Dataset):
    def __init__(self,n,seed):self.n=n;self.seed=seed
    def __len__(self):return self.n
    def __getitem__(self,i):
        rng=random.Random(self.seed+i);label=i%11
        return torch.from_numpy(render(label,rng)[None]),label


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('.local/led-glyph-training'))
    parser.add_argument('--seed',type=int,default=20261114)
    parser.add_argument('--epochs',type=int,default=12)
    parser.add_argument('--samples',type=int,default=11000)
    parser.add_argument('--threads',type=int,default=4)
    args=parser.parse_args()
    if min(args.epochs,args.samples,args.threads)<1:parser.error('epochs, samples and threads must be positive')
    args.output.mkdir(parents=True,exist_ok=True)
    torch.manual_seed(args.seed);torch.set_num_threads(args.threads);cv2.setNumThreads(1)
    model=GlyphNet();optim=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    start=time.perf_counter();history=[]
    for epoch in range(args.epochs):
        model.train();loss_sum=0
        loader=DataLoader(Synth(args.samples,args.seed+epoch*100000),batch_size=128,shuffle=True)
        for images,labels in loader:
            logits=model(images);loss=nn.functional.cross_entropy(logits,labels)
            optim.zero_grad();loss.backward();optim.step();loss_sum+=float(loss.detach())
        model.eval();correct=0;count=0
        with torch.inference_mode():
            for images,labels in DataLoader(Synth(1100,999999),batch_size=128):
                correct+=int((model(images).argmax(-1)==labels).sum());count+=len(labels)
        record=dict(epoch=epoch+1,loss=loss_sum/len(loader),synthetic_correct=correct,synthetic_total=count,elapsed_s=time.perf_counter()-start)
        history.append(record);print(json.dumps(record),flush=True)
        torch.save(dict(state_dict=model.state_dict(),history=history),args.output/'glyph-specialist.pth')
        (args.output/'training-history.json').write_text(json.dumps(history,indent=2))
    target=args.output/'led_glyph.onnx'
    torch.onnx.export(model,torch.zeros((1,1,48,32)),str(target),input_names=['glyph'],output_names=['logits'],opset_version=17,dynamic_axes={'glyph':{0:'batch'},'logits':{0:'batch'}},dynamo=False)
    import hashlib
    (args.output/'training-run.json').write_text(json.dumps(dict(seed=args.seed,epochs=args.epochs,
        samples=args.samples,torch=torch.__version__,numpy=np.__version__,opencv=cv2.__version__,
        model_sha256=hashlib.sha256(target.read_bytes()).hexdigest()),indent=2))
    print('exported',target,flush=True)


if __name__=='__main__':main()
