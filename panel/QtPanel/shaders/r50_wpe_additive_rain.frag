#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 particleCenter;
    vec2 particleExtent;
    float particleAlpha;
    float bandCode;
    float progress;
    float coreWidthFraction;
    float coreHeightFraction;
} ubuf;

layout(binding = 1) uniform sampler2D depthMask;
layout(binding = 2) uniform sampler2D rainVisibility;
layout(binding = 3) uniform sampler2D keepoutMask;

void main()
{
    vec2 local = qt_TexCoord0;
    vec2 globalUv = ubuf.particleCenter + (local - vec2(0.5)) * ubuf.particleExtent;
    float depth = texture(depthMask, clamp(globalUv, vec2(0.0), vec2(1.0))).r;
    vec3 visibilityBands = texture(
        rainVisibility, clamp(globalUv, vec2(0.0), vec2(1.0))
    ).rgb;
    float visibility = ubuf.bandCode < 0.5 ? visibilityBands.r
                     : ubuf.bandCode < 1.5 ? visibilityBands.g
                     : visibilityBands.b;
    float keepout = texture(
        keepoutMask, clamp(globalUv, vec2(0.0), vec2(1.0))
    ).r;
    // RGB visibility remains the categorical placement/occlusion authority.
    // The continuous depth map only weights perspective within each band; its
    // production minimum is nonzero, so treating it as a binary .02 gate was
    // both misleading and visually inert.
    float farDepthAuthority = 1.0 - smoothstep(0.28, 0.72, depth);
    float middleDepthAuthority = 1.0 - smoothstep(
        0.18, 0.50, abs(depth - 0.52)
    );
    float nearDepthAuthority = smoothstep(0.28, 0.78, depth);
    float selectedDepthAuthority = ubuf.bandCode < 0.5 ? farDepthAuthority
                                 : ubuf.bandCode < 1.5 ? middleDepthAuthority
                                 : nearDepthAuthority;
    float depthWeight = mix(0.65, 1.0, selectedDepthAuthority);
    // A swept keepout has a deliberately feathered edge.  Close it before
    // optical gain so rain cannot form a bright dry halo around the moving
    // hand/cloth, while the categorical RGB visibility map remains the
    // placement authority everywhere else.
    float keepoutGate = 1.0 - smoothstep(0.12, 0.58, keepout);
    float allowed = depthWeight * visibility * keepoutGate;
    if (allowed <= 0.001) {
        fragColor = vec4(0.0);
        return;
    }

    // Convert the expanded delegate back into reference-space core
    // coordinates.  This preserves the far/middle/near 1/1.6/3.2-pixel
    // cores and their 8/18/46-pixel lengths while allowing the surrounding
    // box to carry a finite soft shoulder.
    float coreX = abs(local.x - 0.5) * 2.0
                / max(ubuf.coreWidthFraction, 0.001);
    float coreY = (local.y - 0.5) / max(ubuf.coreHeightFraction, 0.001) + 0.5;
    float taperedWidth = mix(0.48, 0.96, clamp(coreY, 0.0, 1.0));
    float coreProfile = 1.0 - smoothstep(0.62, taperedWidth, coreX);
    float coreTrail = smoothstep(0.0, 0.06, coreY)
                    * (1.0 - smoothstep(0.88, 1.0, coreY));
    coreProfile *= coreTrail;

    float shoulderVertical = smoothstep(0.0, 0.08, local.y)
                           * (1.0 - smoothstep(0.84, 1.0, local.y));
    float shoulderProfile = exp(-pow((local.x - 0.5) / 0.38, 2.0))
                          * shoulderVertical;
    float broken = 0.86 + 0.14 * sin(
        local.y * 27.0 + ubuf.particleCenter.x * 119.0
    );
    float lifeFade = smoothstep(0.0, 0.04, ubuf.progress)
                   * (1.0 - smoothstep(0.94, 1.0, ubuf.progress));

    float farOpticalDensity = clamp(
        0.30 + ubuf.particleAlpha * 1.00, 0.34, 0.60
    );
    float middleOpticalDensity = clamp(
        0.27 + ubuf.particleAlpha * 0.85, 0.31, 0.55
    );
    float nearOpticalDensity = clamp(
        0.24 + ubuf.particleAlpha * 0.70, 0.28, 0.48
    );
    float bandOpticalDensity = ubuf.bandCode < 0.5 ? farOpticalDensity
                               : ubuf.bandCode < 1.5 ? middleOpticalDensity
                               : nearOpticalDensity;
    float shoulderOpticalDensity = ubuf.bandCode < 0.5 ? 0.10
                                   : ubuf.bandCode < 1.5 ? 0.12 : 0.14;
    float alpha = (coreProfile * bandOpticalDensity
                 + shoulderProfile * shoulderOpticalDensity)
                * broken * lifeFade * allowed;
    alpha = clamp(alpha, 0.0, 0.62);
    vec3 color = mix(vec3(0.36, 0.52, 0.62), vec3(0.76, 0.87, 0.93), local.y);
    fragColor = vec4(color * alpha, alpha) * ubuf.qt_Opacity;
}
