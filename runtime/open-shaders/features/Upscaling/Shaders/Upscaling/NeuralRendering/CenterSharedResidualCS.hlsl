Texture2D<float4> CenterNeural : register(t0);
Texture2D<float4> CenterBase : register(t1);
RWTexture2D<float4> CenterResidual : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	uint width, height;
	CenterResidual.GetDimensions(width, height);
	if (id.x >= width || id.y >= height)
		return;
	CenterResidual[id.xy] = CenterNeural.Load(int3(id.xy, 0)) -
		CenterBase.Load(int3(id.xy, 0));
}
