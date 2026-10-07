#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    vec2 maskTexelSize;
    float foregroundPass;
    float time;
} ubuf;

layout(binding = 1) uniform sampler2D trailMask;
layout(binding = 2) uniform sampler2D sceneSource;
layout(binding = 3) uniform sampler2D wetNormal;
layout(binding = 4) uniform sampler2D depthMask;

vec3 depthChannels(vec2 uv)
{
    // The live Canvas is only a compact particle-data raster: R is far, G is
    // middle and B is near/lens. It is never presented as the visible rain.
    return clamp(texture(trailMask, clamp(uv, vec2(0.0), vec2(1.0))).rgb,
                 vec3(0.0), vec3(1.0));
}

float rawCoverage(vec2 uv)
{
    vec3 bands = depthChannels(uv);
    return clamp(bands.r + bands.g + bands.b, 0.0, 1.0);
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec3 bands = depthChannels(uv);
    float raw = clamp(bands.r + bands.g + bands.b, 0.0, 1.0);
    if (raw <= 0.0001) {
        fragColor = vec4(0.0);
        return;
    }

    // Reconstruct a soft droplet normal from the procedural trail silhouette.
    // A rights-safe generated roughness field breaks uniform computer-straight
    // highlights without importing Wallpaper Engine's stock textures.
    vec2 texel = max(ubuf.maskTexelSize, vec2(0.000001));
    vec2 silhouetteGradient = vec2(
        rawCoverage(uv - vec2(texel.x, 0.0))
            - rawCoverage(uv + vec2(texel.x, 0.0)),
        rawCoverage(uv - vec2(0.0, texel.y))
            - rawCoverage(uv + vec2(0.0, texel.y))
    );
    vec2 roughness = texture(
        wetNormal,
        fract(uv * vec2(2.3, 2.1) + vec2(ubuf.time * 0.006, 0.0))
    ).rg * 2.0 - 1.0;
    vec2 dropletNormal = silhouetteGradient * 1.85 + roughness * (0.18 + raw * 0.12);
    float normalLength = length(dropletNormal);
    if (normalLength > 0.0001) {
        dropletNormal /= normalLength;
    }

    float bandTotal = max(raw, 0.0001);
    float depthResponse = dot(bands, vec3(0.62, 1.08, 1.72)) / bandTotal;
    float displacementPixels = depthResponse * (0.55 + raw * 1.15);
    vec2 pixelSize = 1.0 / max(ubuf.viewportSize, vec2(1.0));
    vec2 refractedUv = clamp(
        uv + dropletNormal * displacementPixels * pixelSize,
        vec2(0.0), vec2(1.0)
    );

    // Convert the low-alpha data raster into a readable optical body. This
    // preserves all service-side population/depth decisions while preventing
    // far streaks from disappearing during scene compositing.
    float body = 1.0 - exp(-raw * 3.65);
    float edge = smoothstep(0.025, 0.46, length(silhouetteGradient));
    float movingGlint = 0.82 + 0.18 * sin(
        uv.y * ubuf.viewportSize.y * 0.085
        - uv.x * ubuf.viewportSize.x * 0.031
        + ubuf.time * 4.2
    );
    float specular = clamp(edge * 0.78 + body * body * 0.14, 0.0, 1.0)
                     * movingGlint;

    if (ubuf.foregroundPass < 0.5) {
        vec3 refracted = texture(sceneSource, refractedUv).rgb;
        vec3 coolSpecular = vec3(0.54, 0.76, 0.91) * specular * 0.34;
        float alpha = clamp(body * 0.78, 0.0, 0.72);
        vec3 opticalColor = refracted + coolSpecular;
        fragColor = vec4(opticalColor * alpha, alpha) * ubuf.qt_Opacity;
        return;
    }

    // Near drops sit in lens space in front of the scene. Their larger lens
    // displacement is already coupled in r50_live_surface. Keep this final
    // pass rim/highlight-only: re-compositing a pre-character scene sample here
    // can erase anatomy and can flash black while that source texture warms up.
    float depthAuthority = texture(depthMask, uv).r;
    float nearAuthority = smoothstep(0.78, 0.96, depthAuthority);
    float nearBody = 1.0 - exp(-bands.b * 4.25);
    float alpha = clamp((nearBody * 0.12 + specular * 0.28) * nearAuthority,
                        0.0, 0.34);
    vec3 lensColor = mix(vec3(0.56, 0.72, 0.81),
                         vec3(0.93, 0.98, 1.0),
                         clamp(specular * 1.55, 0.0, 1.0));
    fragColor = vec4(lensColor * alpha, alpha) * ubuf.qt_Opacity;
}
