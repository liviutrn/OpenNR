// OpenNR 2.20.1-v01 — pack two per-eye R32 depth guides into a horizontal atlas.
cbuffer AtlasPackCB : register(b0)
{
    uint EyeWidth;
    uint EyeHeight;
    uint GuardWidth;
    uint SourceOffsetX;
    uint SourceOffsetY;
    uint AtlasWidth;
    uint AtlasHeight;
    uint _pad0;
};
Texture2D<float> LeftTex : register(t0);
Texture2D<float> RightTex : register(t1);
RWTexture2D<float> AtlasTex : register(u0);
[numthreads(8,8,1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= AtlasWidth || tid.y >= AtlasHeight) return;
    const uint y = SourceOffsetY + min(tid.y, EyeHeight - 1);
    if (tid.x < EyeWidth) {
        AtlasTex[tid.xy] = LeftTex.Load(int3(SourceOffsetX + tid.x, y, 0));
        return;
    }
    const uint rightStart = EyeWidth + GuardWidth;
    if (tid.x >= rightStart) {
        AtlasTex[tid.xy] = RightTex.Load(int3(SourceOffsetX + (tid.x - rightStart), y, 0));
        return;
    }
    const uint guardX = tid.x - EyeWidth;
    const uint leftGuard = GuardWidth / 2;
    AtlasTex[tid.xy] = guardX < leftGuard ?
        LeftTex.Load(int3(SourceOffsetX + EyeWidth - 1, y, 0)) :
        RightTex.Load(int3(SourceOffsetX, y, 0));
}
