extern "C" __global__ void unpack_rgb(const unsigned char* source,float* rgb,int w,int h) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=w*h)return;
    for(int c=0;c<3;++c)rgb[c*w*h+i]=source[4*i+c]*(1.0f/255.0f);
}
__device__ float half_value(unsigned short bits) {
    unsigned exponent=(bits>>10)&31,mantissa=bits&1023;float sign=(bits&32768)?-1.f:1.f;
    if(exponent==31)return __int_as_float((bits&32768)?0xff800000:0x7f800000);
    if(exponent==0)return sign*ldexpf((float)mantissa,-24);
    return sign*ldexpf(1.f+mantissa/1024.f,(int)exponent-15);
}
__device__ void guides_at(const float* depth,const unsigned short* motion,int gw,int gh,float x,float y,float sx,float sy,float* out) {
    int ix=(int)floorf(x),iy=(int)floorf(y);float fx=x-ix,fy=y-iy;
    float ds=0,ms=0,d=0,mx=0,my=0;
    for(int j=0;j<2;++j)for(int i=0;i<2;++i){
        int px=max(0,min(gw-1,ix+i)),py=max(0,min(gh-1,iy+j)),index=py*gw+px;
        float weight=(i?fx:1-fx)*(j?fy:1-fy),dv=depth[index];
        if(isfinite(dv)&&dv>=0&&dv<=1){d+=weight*dv;ds+=weight;}
        float vx=half_value(motion[2*index]),vy=half_value(motion[2*index+1]);
        if(isfinite(vx)&&isfinite(vy)&&fabsf(vx)<=.25f&&fabsf(vy)<=.25f){
            mx+=weight*fminf(1.f,fmaxf(-1.f,vx*sx));my+=weight*fminf(1.f,fmaxf(-1.f,vy*sy));ms+=weight;
        }
    }
    out[0]=ds>.999f?d/fmaxf(ds,1e-6f):0;out[1]=ms>.999f?mx/fmaxf(ms,1e-6f):0;out[2]=ms>.999f?my/fmaxf(ms,1e-6f):0;
    out[3]=ds>.999f?1.f:0;out[4]=ms>.999f?1.f:0;
}
extern "C" __global__ void prepare_guides(const float* depth,const unsigned short* motion,float* output,int gw,int gh,int ow,int oh,float sx,float sy){
    int i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=ow*oh)return;int x=i%ow,y=i/ow;float values[5];
    guides_at(depth,motion,gw,gh,(x+.5f)*gw/ow-.5f,(y+.5f)*gh/oh-.5f,sx,sy,values);
    for(int c=0;c<5;++c)output[c*ow*oh+i]=values[c];
}
extern "C" __global__ void prepare_context(const unsigned char* color,const float* depth,const unsigned short* motion,float* output,int w,int h,int gw,int gh,float sx,float sy){
    int i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=96*96)return;int x=i%96,y=i/96,bw=w/96,bh=h/96;
    // Native 2496x2688 maps exactly to 26x28 boxes; mimic separable RGB8 BOX rounding.
    for(int c=0;c<3;++c){unsigned sum=0;for(int yy=0;yy<bh;++yy){unsigned row=0;for(int xx=0;xx<bw;++xx)row+=color[4*((y*bh+yy)*w+x*bw+xx)+c];sum+=(unsigned)floorf((float)row/bw+.5f);}output[c*96*96+i]=floorf((float)sum/bh+.5f)/255.f;}
    float values[5];guides_at(depth,motion,gw,gh,(x+.5f)*gw/96-.5f,(y+.5f)*gh/96-.5f,sx,sy,values);
    for(int c=0;c<5;++c)output[(c+3)*96*96+i]=values[c];
}
extern "C" __global__ void pack_output(const float* input,unsigned char* rgba,int w,int h){
    int i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=w*h)return;
    for(int c=0;c<3;++c)rgba[4*i+c]=(unsigned char)__float2int_rn(fminf(1.f,fmaxf(0.f,input[c*w*h+i]))*255.f);
    rgba[4*i+3]=255;
}
