#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 sceneRect;
    vec2 depthTexel;
    vec2 itemSize;
    vec4 lifecycleParams;
} ubuf;

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D depthMask;

void main()
{
    vec2 sceneUv = ubuf.sceneRect.xy + qt_TexCoord0 * ubuf.sceneRect.zw;
    float center = texture(depthMask, sceneUv).r;
    float left = texture(depthMask, sceneUv - vec2(ubuf.depthTexel.x, 0.0)).r;
    float right = texture(depthMask, sceneUv + vec2(ubuf.depthTexel.x, 0.0)).r;
    float above = texture(depthMask, sceneUv - vec2(0.0, ubuf.depthTexel.y)).r;
    float below = texture(depthMask, sceneUv + vec2(0.0, ubuf.depthTexel.y)).r;
    float depthAuthority = (center * 2.0 + left + right + above + below) / 6.0;
    float protectedVisibility = smoothstep(0.035, 0.22, depthAuthority);

    float opening = smoothstep(0.0, 1.0, ubuf.lifecycleParams.x);
    float collapse = smoothstep(0.0, 1.0, ubuf.lifecycleParams.y);
    float seed = ubuf.lifecycleParams.w;
    float irregularity = sin(qt_TexCoord0.x * 31.0 + seed * 12.7) * 0.025
                        + sin(qt_TexCoord0.x * 73.0 - seed * 8.3) * 0.012;
    float openingFront = mix(0.96, -0.08, opening) + irregularity;
    float openingGate = smoothstep(openingFront - 0.055,
                                   openingFront + 0.055,
                                   qt_TexCoord0.y);
    float collapseFront = mix(-0.14, 0.76, collapse) - irregularity;
    float collapseGate = smoothstep(collapseFront - 0.070,
                                    collapseFront + 0.080,
                                    qt_TexCoord0.y);

    vec4 color = texture(source, qt_TexCoord0);
    color.a *= protectedVisibility * openingGate * collapseGate;
    fragColor = color * ubuf.qt_Opacity;
}
