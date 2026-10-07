#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 sceneRect;
    vec2 depthTexel;
    vec2 itemSize;
    vec4 lifecycleParams;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    vec4 position = qt_Vertex;
    float opening = smoothstep(0.0, 1.0, ubuf.lifecycleParams.x);
    float collapse = smoothstep(0.0, 1.0, ubuf.lifecycleParams.y);
    float age = ubuf.lifecycleParams.z;
    float seed = ubuf.lifecycleParams.w;
    float upperWeight = pow(max(0.0, 1.0 - qt_MultiTexCoord0.y), 1.35);

    // Keep the crown's water contact pinned while it grows from a narrow
    // contact sheet into its full silhouette and then loses height during
    // collapse. A low-amplitude seeded bend prevents a rigid scaled-photo
    // appearance without changing the impact-owned base location.
    float baseAnchor = ubuf.itemSize.y * 0.82;
    float verticalScale = (0.18 + opening * 0.82) * (1.0 - collapse * 0.38);
    position.y = baseAnchor + (position.y - baseAnchor) * verticalScale;
    float horizontalScale = 0.72 + opening * 0.28 + collapse * 0.08;
    position.x = ubuf.itemSize.x * 0.5
                 + (position.x - ubuf.itemSize.x * 0.5) * horizontalScale;
    float liveAmount = opening * (1.0 - collapse * 0.62);
    position.x += sin(qt_MultiTexCoord0.y * 14.0 + age * 8.0 + seed * 6.283)
                  * ubuf.itemSize.x * 0.012 * upperWeight * liveAmount;
    position.y += sin(qt_MultiTexCoord0.x * 17.0 - age * 6.5 + seed * 4.13)
                  * ubuf.itemSize.y * 0.010 * upperWeight * liveAmount;
    gl_Position = ubuf.qt_Matrix * position;
}
