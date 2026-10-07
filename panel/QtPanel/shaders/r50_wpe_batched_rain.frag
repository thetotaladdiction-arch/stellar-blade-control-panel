#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    vec2 maskTexelSize;
    float rainIntensity;
    float sceneTime;
    float diagnosticMode;
} ubuf;

layout(binding = 1) uniform sampler2D perspectiveTrailMask;
layout(binding = 2) uniform sampler2D depthMask;
layout(binding = 3) uniform sampler2D rainVisibility;
layout(binding = 4) uniform sampler2D keepoutMask;

vec3 depthChannels(vec4 sampleValue)
{
    return clamp(sampleValue.rgb, vec3(0.0), vec3(1.0));
}

vec3 samplePerspectiveBands(vec2 uv)
{
    return depthChannels(texture(
        perspectiveTrailMask, clamp(uv, vec2(0.0), vec2(1.0))
    ));
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 texel = max(ubuf.maskTexelSize, vec2(0.000001));
    vec2 featherOffset = vec2(texel.x, 0.0);
    vec3 perspectiveBands = samplePerspectiveBands(uv);
    vec3 featherPositive = samplePerspectiveBands(uv + featherOffset);
    vec3 featherNegative = samplePerspectiveBands(uv - featherOffset);
    // One physical particle still owns one decoded silhouette. A bounded
    // one-pixel optical feather restores the antialiased edge lost at panel
    // resolution without adding a card, second mask, or shifted rain track.
    const vec3 coreExposure = vec3(2.15);
    const vec3 featherExposure = vec3(0.60);
    vec3 projectedBands = perspectiveBands * coreExposure;
    projectedBands = max(
        projectedBands,
        max(featherPositive, featherNegative)
            * coreExposure * featherExposure
    );

    float bandTotal = clamp(
        projectedBands.r + projectedBands.g + projectedBands.b,
        0.0, 1.0
    );
    if (bandTotal <= 0.0001) {
        fragColor = vec4(0.0);
        return;
    }

    vec3 bandShare = projectedBands / max(bandTotal, 0.0001);
    if (ubuf.diagnosticMode > 0.5) {
        float diagnosticAlpha = smoothstep(0.002, 0.06, bandTotal);
        vec3 diagnosticColor = clamp(bandShare * 1.15, vec3(0.0), vec3(1.0));
        fragColor = vec4(
            diagnosticColor * diagnosticAlpha, diagnosticAlpha
        ) * ubuf.qt_Opacity;
        return;
    }

    // Visibility RGB is categorical placement/occlusion authority. The
    // physical emitter already chose a valid band position, so a present
    // channel gates the particle without attenuating it a second time.
    vec3 visibilityBands = texture(
        rainVisibility, clamp(uv, vec2(0.0), vec2(1.0))
    ).rgb;
    float visibilityAuthority = dot(bandShare, visibilityBands);
    float visibilityPresence = smoothstep(0.005, 0.04, visibilityAuthority);
    float keepout = texture(
        keepoutMask, clamp(uv, vec2(0.0), vec2(1.0))
    ).r;
    // The painted keepout is categorical anatomy/prop occlusion. Sample its
    // exact point authority so protected pixels remain dry without expanding
    // the mask into the first valid halo ring.
    float keepoutGate = 1.0 - step(0.58, keepout);
    float authoredCoverage = bandTotal * visibilityPresence * keepoutGate;
    if (authoredCoverage <= 0.0001) {
        fragColor = vec4(0.0);
        return;
    }

    // The finite envelope above is presentation-only: the Canvas still owns
    // each particle's ID, alpha, trajectory, and explicit quad geometry. This
    // continuous depth grade then preserves within-band ordering without
    // erasing any categorical authority.
    float depth = texture(
        depthMask, clamp(uv, vec2(0.0), vec2(1.0))
    ).r;
    float depthProjection = mix(0.92, 1.08, depth);
    float rainGain = clamp(ubuf.rainIntensity, 0.0, 2.0);
    // The extracted WPE particle/drop material initializes color at 255.
    // Particle alpha and the sprite silhouette own attenuation; applying an
    // extra blue-gray color multiplier here discards authored rain energy.
    const vec3 perspectiveMaterialColor = vec3(1.0);
    float authoredPremul = authoredCoverage * depthProjection * rainGain;
    vec3 additivePremul = perspectiveMaterialColor
                        * authoredPremul;

    // Wallpaper Engine's perspective `particle/drop` material is additive.
    // Refraction belongs only to the separate screen/lens-rain hierarchy.
    fragColor = vec4(additivePremul, 0.0) * ubuf.qt_Opacity;
}
