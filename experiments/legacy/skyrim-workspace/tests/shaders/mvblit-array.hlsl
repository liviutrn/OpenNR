Texture2DArray<float2>   src : register(t0);
RWTexture2DArray<float2> dst : register(u0);

[numthreads(8,8,1)]
void main(uint3 id : SV_DispatchThreadID)
{
    uint w, h, layers;
    dst.GetDimensions(w, h, layers);
    if (id.x < w && id.y < h && id.z < layers)
        dst[id] = src[id];
}
