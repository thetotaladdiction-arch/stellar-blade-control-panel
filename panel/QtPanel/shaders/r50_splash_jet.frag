#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 sceneRect;
    vec2 depthTexel;
    vec4 dropletParams;
} ubuf;

layout(binding = 1) uniform sampler2D depthMask;

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

    // A tiny asymmetric SDF reads as a moving bead of water without needing
    // a sprite sheet. The stable event/index seed changes its contour, not
    // its trajectory; world position remains wholly owned by the simulation.
    vec2 p = qt_TexCoord0 * 2.0 - 1.0;
    float seed = ubuf.dropletParams.x;
    float interior = max(0.0, 1.0 - abs(p.y));
    p.x += sin((p.y * 1.7 + seed * 5.0) * 3.14159265) * 0.055 * interior;
    p.x *= 1.0 + 0.10 * p.y;
    float distanceToEdge = length(p);
    float body = 1.0 - smoothstep(0.72, 1.0, distanceToEdge);
    float rim = smoothstep(0.48, 0.82, distanceToEdge)
              * (1.0 - smoothstep(0.82, 0.99, distanceToEdge));
    float glint = exp(-18.0 * dot(p - vec2(-0.24, -0.30),
                                 p - vec2(-0.24, -0.30)));

    float alpha = body * protectedVisibility * (0.76 + 0.12 * rim);
    vec3 water = mix(vec3(0.31, 0.47, 0.53), vec3(0.72, 0.87, 0.91),
                     clamp(rim * 0.72 + glint * 0.82, 0.0, 1.0));
    fragColor = vec4(water * alpha, alpha) * ubuf.qt_Opacity;
}
