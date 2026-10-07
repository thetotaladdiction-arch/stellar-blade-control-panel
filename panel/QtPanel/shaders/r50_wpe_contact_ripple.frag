#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    float rippleDisplacementPixels;
    float contactRippleEnabled;
    float sceneTime;
    float waterRippleSpeed;
    vec4 ripple0;
    vec4 ripple1;
    vec4 ripple2;
    vec4 ripple3;
    vec4 ripple4;
    vec4 ripple5;
    vec4 ripple6;
    vec4 ripple7;
    float rippleRingCount0;
    float rippleRingCount1;
    float rippleRingCount2;
    float rippleRingCount3;
    float rippleRingCount4;
    float rippleRingCount5;
    float rippleRingCount6;
    float rippleRingCount7;
} ubuf;

layout(binding = 1) uniform sampler2D surfaceSource;
layout(binding = 2) uniform sampler2D surfaceResponse;
layout(binding = 3) uniform sampler2D waterRippleNormal;

vec3 sampleWpeWaterNormal(vec2 coordinates)
{
    // Match the decoded WPE Water Ripple sampler used by the continuous
    // surface pass, including its two counter-scrolling repeated normals.
    vec2 secondaryCoordinates = coordinates * 1.333;
    float speed = ubuf.waterRippleSpeed;
    float animationPhase = ubuf.sceneTime * speed * speed;
    vec4 rippleCoordinates;
    rippleCoordinates.xy = coordinates + vec2(animationPhase);
    rippleCoordinates.zw = secondaryCoordinates - vec2(animationPhase);
    float sourceAspect = ubuf.viewportSize.x / max(ubuf.viewportSize.y, 1.0);
    rippleCoordinates.xz *= sourceAspect;
    vec3 n1 = texture(waterRippleNormal, fract(rippleCoordinates.xy)).xyz
            * 2.0 - 1.0;
    vec3 n2 = texture(waterRippleNormal, fract(rippleCoordinates.zw)).xyz
            * 2.0 - 1.0;
    return normalize(vec3(n1.xy + n2.xy, n1.z));
}

float compactRing(
    float ellipseDistancePixels,
    float radiusPixels,
    float ellipseGradientLength,
    float halfWidthPixels
)
{
    // Convert the ellipse's signed implicit distance back to screen pixels.
    // This keeps both the horizontal and foreshortened vertical portions of
    // the wave in the same compact 1--2 px band.
    float signedScreenDistancePixels = (
        ellipseDistancePixels - radiusPixels
    ) / max(ellipseGradientLength, 0.001);
    float normalizedDistance = abs(signedScreenDistancePixels)
                             / max(halfWidthPixels, 0.55);
    return 1.0 - smoothstep(0.55, 1.0, normalizedDistance);
}

float compactNormal(
    float ellipseDistancePixels,
    float radiusPixels,
    float ellipseGradientLength,
    float halfWidthPixels
)
{
    // A water-wave normal has a crest and trough on opposite sides of the
    // displaced ridge. Each lobe remains a compact 2--3 px band; separating
    // the lobes prevents opposite sub-pixel warps from cancelling at review
    // resolution without drawing a synthetic bright ring.
    float lobeHalfWidthPixels = clamp(halfWidthPixels, 1.20, 1.80);
    float lobeOffsetPixels = lobeHalfWidthPixels * 0.90;
    return compactRing(
        ellipseDistancePixels,
        max(radiusPixels - lobeOffsetPixels, lobeHalfWidthPixels),
        ellipseGradientLength,
        lobeHalfWidthPixels
    ) - compactRing(
        ellipseDistancePixels,
        radiusPixels + lobeOffsetPixels,
        ellipseGradientLength,
        lobeHalfWidthPixels
    );
}

float cyclicTurnDistance(float a, float b)
{
    float distance = abs(a - b);
    return min(distance, 1.0 - distance);
}

float taperedArc(float turn, float center, float halfWidth)
{
    float distance = cyclicTurnDistance(turn, fract(center));
    return 1.0 - smoothstep(halfWidth * 0.84, halfWidth, distance);
}

float brokenArcKeep(float turn, float arcMaterialSeed, float ringOrdinal)
{
    // Each physical wavefront owns different sparse sectors. Reusing one
    // mask across every radius creates parallel Wi-Fi/radar contours even
    // when the individual sectors are broken.
    float ringPhase = fract(ringOrdinal * 0.12);
    float materialShift = (arcMaterialSeed - 0.5) * 0.04;
    float widthScale = mix(0.92, 1.06, arcMaterialSeed);
    float family0 = taperedArc(
        turn, 0.035 + ringPhase + materialShift, 0.160 * widthScale
    );
    float family1 = taperedArc(
        turn, 0.525 + ringPhase - materialShift, 0.130 * widthScale
    );
    float families = max(family0, family1);
    float wpeTailVariation = mix(0.82, 1.0, arcMaterialSeed);
    return families * wpeTailVariation;
}

void accumulateRipple(
    vec4 ripple,
    float ringCount,
    vec2 uv,
    vec2 localMaterialNormal,
    inout vec2 displacementPixels,
    inout float surfaceNormal
)
{
    float eventStrength = clamp(ripple.w, 0.0, 1.0);
    float radiusPixels = ripple.z * ubuf.viewportSize.x;
    if (eventStrength <= 0.0 || radiusPixels <= 0.0
            || ringCount < 1.5 || ringCount > 4.5) {
        return;
    }

    vec2 deltaPixels = (uv - ripple.xy) * ubuf.viewportSize;
    // The registered receiver is a receding floor plane. Preserve the packet
    // radius as the horizontal semi-major axis and foreshorten only Y; a
    // screen-space circle reads as a HUD reticle on this scene.
    float floorPerspectiveAspect = mix(
        0.32, 0.42, smoothstep(0.58, 0.94, clamp(ripple.y, 0.0, 1.0))
    );
    vec2 ellipseDeltaPixels = vec2(
        deltaPixels.x, deltaPixels.y / floorPerspectiveAspect
    );
    float ellipseDistancePixels = length(ellipseDeltaPixels);
    vec2 ellipseGradient = vec2(
        deltaPixels.x,
        deltaPixels.y / (floorPerspectiveAspect * floorPerspectiveAspect)
    ) / max(ellipseDistancePixels, 0.001);
    float ellipseGradientLength = length(ellipseGradient);
    vec2 radialDirection = ellipseGradient
                         / max(ellipseGradientLength, 0.001);
    // Sub-pixel roughness comes from the decoded WPE material normal. Each
    // radius receives a different signed amount, so nearby fronts do not
    // trace the same smooth parallel curve. The displacement is strictly
    // bounded and cannot move the physical packet or change its scale.
    float radialRoughnessPixels = clamp(
        dot(localMaterialNormal, vec2(0.61, -0.39)) * 0.75,
        -0.75, 0.75
    );
    float ringDistance0 = ellipseDistancePixels + radialRoughnessPixels * 0.55;
    float ringDistance1 = ellipseDistancePixels - radialRoughnessPixels * 0.80;
    float ringDistance2 = ellipseDistancePixels + radialRoughnessPixels;
    float ringDistance3 = ellipseDistancePixels - radialRoughnessPixels * 0.65;
    float halfWidthPixels = clamp(radiusPixels * 0.028, 1.20, 1.80);
    // Distinct wavefronts retain the packet's 2--4 ring topology. The old
    // 3.6 px spacing packed opposite warps into the same downsampled pixel.
    float ringSpacingPixels = clamp(radiusPixels * 0.12, 7.0, 16.0);
    float ring1Active = step(
        ringSpacingPixels + halfWidthPixels * 2.0, radiusPixels
    ) * step(1.5, ringCount);
    float ring2Active = step(
        ringSpacingPixels * 2.0 + halfWidthPixels * 2.0, radiusPixels
    ) * step(2.5, ringCount);
    float ring3Active = step(
        ringSpacingPixels * 3.0 + halfWidthPixels * 2.0, radiusPixels
    ) * step(3.5, ringCount);
    float ring0 = compactRing(
        ringDistance0, radiusPixels,
        ellipseGradientLength, halfWidthPixels
    );
    float ring1 = compactRing(
        ringDistance1,
        max(radiusPixels - ringSpacingPixels, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.92
    ) * ring1Active;
    float ring2 = compactRing(
        ringDistance2,
        max(radiusPixels - ringSpacingPixels * 2.0, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.86
    ) * ring2Active;
    float ring3 = compactRing(
        ringDistance3,
        max(radiusPixels - ringSpacingPixels * 3.0, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.80
    ) * ring3Active;

    float normal0 = compactNormal(
        ringDistance0, radiusPixels,
        ellipseGradientLength, halfWidthPixels
    );
    float normal1 = compactNormal(
        ringDistance1,
        max(radiusPixels - ringSpacingPixels, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.92
    ) * ring1Active;
    float normal2 = compactNormal(
        ringDistance2,
        max(radiusPixels - ringSpacingPixels * 2.0, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.86
    ) * ring2Active;
    float normal3 = compactNormal(
        ringDistance3,
        max(radiusPixels - ringSpacingPixels * 3.0, halfWidthPixels),
        ellipseGradientLength,
        halfWidthPixels * 0.80
    ) * ring3Active;
    const float pi = 3.141592654;
    float arcAngle = atan(ellipseDeltaPixels.y, ellipseDeltaPixels.x);
    float turn = (arcAngle + pi) / (2.0 * pi);
    vec2 arcSeedCoordinates = ripple.xy
                            + vec2(ripple.z * 0.37, -ripple.z * 0.23);
    vec3 arcMaterialNormal = sampleWpeWaterNormal(arcSeedCoordinates);
    float arcMaterialSeed = dot(abs(arcMaterialNormal.xy), vec2(0.61, 0.39));
    float arcKeep0 = brokenArcKeep(turn, arcMaterialSeed, 0.0);
    float arcKeep1 = brokenArcKeep(turn, arcMaterialSeed, 1.0);
    float arcKeep2 = brokenArcKeep(turn, arcMaterialSeed, 2.0);
    float arcKeep3 = brokenArcKeep(turn, arcMaterialSeed, 3.0);
    float localArcBreakup = mix(
        0.48, 1.0,
        smoothstep(
            0.18, 0.72,
            abs(dot(localMaterialNormal, vec2(0.43, 0.57)))
        )
    );
    arcKeep0 *= localArcBreakup;
    arcKeep1 *= localArcBreakup;
    arcKeep2 *= localArcBreakup;
    arcKeep3 *= localArcBreakup;
    // Hand the contact to the scene-derived floor wave as the photographic
    // crown begins collapsing. Frame 14 is late enough to preserve the crown
    // silhouette and early enough to prevent its low remnant becoming a card.
    float postWindowActivation = smoothstep(0.039, 0.043, ripple.z);

    // Alternate pressure crests and troughs. Every band uses compact support,
    // so adding topology increases local ring coverage without global warp.
    float radialDisplacement = (
        ring0 * arcKeep0
        - ring1 * 0.72 * arcKeep1
        + ring2 * 0.50 * arcKeep2
        - ring3 * 0.28 * arcKeep3
    ) * eventStrength * postWindowActivation;
    displacementPixels += radialDirection * radialDisplacement;
    surfaceNormal += (
        normal0 * arcKeep0
        - normal1 * 0.72 * arcKeep1
        + normal2 * 0.50 * arcKeep2
        - normal3 * 0.28 * arcKeep3
    ) * eventStrength * postWindowActivation;
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec4 surfaceColor = texture(surfaceSource, uv);
    if (ubuf.contactRippleEnabled <= 0.0) {
        fragColor = vec4(surfaceColor.rgb, 1.0) * ubuf.qt_Opacity;
        return;
    }

    vec2 pixelSize = 1.0 / max(ubuf.viewportSize, vec2(1.0));
    vec3 wetNormal = sampleWpeWaterNormal(uv);
    vec2 materialWarpPixels = wetNormal.xy * 2.25;
    vec2 materialUv = clamp(
        uv + materialWarpPixels * pixelSize,
        vec2(0.0),
        vec2(1.0)
    );
    vec2 displacementPixels = vec2(0.0);
    float surfaceNormal = 0.0;
    accumulateRipple(ubuf.ripple0, ubuf.rippleRingCount0, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple1, ubuf.rippleRingCount1, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple2, ubuf.rippleRingCount2, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple3, ubuf.rippleRingCount3, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple4, ubuf.rippleRingCount4, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple5, ubuf.rippleRingCount5, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple6, ubuf.rippleRingCount6, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);
    accumulateRipple(ubuf.ripple7, ubuf.rippleRingCount7, materialUv, wetNormal.xy, displacementPixels, surfaceNormal);

    if (dot(displacementPixels, displacementPixels) <= 0.000001
            && abs(surfaceNormal) <= 0.0001) {
        fragColor = vec4(surfaceColor.rgb, 1.0) * ubuf.qt_Opacity;
        return;
    }

    vec2 responseProbeX = vec2(pixelSize.x * 2.0, 0.0);
    vec2 responseProbeY = vec2(0.0, pixelSize.y * 2.0);
    vec4 response = texture(surfaceResponse, uv);
    vec4 responseRight = texture(surfaceResponse, uv + responseProbeX);
    vec4 responseLeft = texture(surfaceResponse, uv - responseProbeX);
    vec4 responseDown = texture(surfaceResponse, uv + responseProbeY);
    vec4 responseUp = texture(surfaceResponse, uv - responseProbeY);
    float reflectionGate = clamp(response.b * response.a, 0.0, 1.0);
    float responseVariation = (
        abs(responseRight.b * responseRight.a - responseLeft.b * responseLeft.a)
        + abs(responseDown.b * responseDown.a - responseUp.b * responseUp.a)
    );
    vec3 sourceRight = texture(surfaceSource, uv + responseProbeX).rgb;
    vec3 sourceLeft = texture(surfaceSource, uv - responseProbeX).rgb;
    vec3 sourceDown = texture(surfaceSource, uv + responseProbeY).rgb;
    vec3 sourceUp = texture(surfaceSource, uv - responseProbeY).rgb;
    vec3 sourceNeighborhood = (
        sourceRight + sourceLeft + sourceDown + sourceUp
    ) * 0.25;
    float sceneVariation = length(surfaceColor.rgb - sourceNeighborhood);
    float roughnessBreakup = smoothstep(
        0.015, 0.18, responseVariation + sceneVariation * 1.5
    );
    float materialSlope = length(wetNormal.xy);
    float materialVariation = max(
        roughnessBreakup,
        smoothstep(0.30, 0.82, materialSlope)
    );
    float reflectionAuthority = step(0.02, reflectionGate);
    float materialBreakup = mix(0.36, 1.0, materialVariation);
    float wetMaterialGate = reflectionAuthority * materialBreakup;

    // Reproject the already-rendered wet surface coherently. A shared scalar
    // bound preserves the source hue (including its blue reflection) instead
    // of clamping RGB independently into chromatic fringes. The neutral
    // material highlight remains visible over a locally flat receiver, while
    // the live source sample supplies all spatial color deformation.
    vec2 refractionVector = displacementPixels
                          + wetNormal.xy * surfaceNormal * 0.45;
    float refractionLength = length(refractionVector);
    refractionVector *= min(1.0, 1.0 / max(refractionLength, 0.001));
    float localDisplacementPixels = clamp(ubuf.rippleDisplacementPixels, 1.0, 2.0);
    vec2 forwardUv = clamp(
        uv + refractionVector * localDisplacementPixels * pixelSize,
        vec2(0.0),
        vec2(1.0)
    );
    vec3 forwardScene = texture(surfaceSource, forwardUv).rgb;
    float waveEnergy = clamp(
        length(displacementPixels) + abs(surfaceNormal), 0.0, 1.0
    );
    float waveSupport = sqrt(waveEnergy);
    vec2 localWaveDirection = normalize(
        refractionVector + vec2(0.0001, -0.0001)
    );
    float localSlope = abs(dot(wetNormal.xy, localWaveDirection));
    float localWaveGate = mix(
        0.30, 1.0, smoothstep(0.18, 0.68, localSlope)
    );
    float responseWeight = min(1.0, 2.2 * waveSupport
                         * wetMaterialGate
                         * localWaveGate
                         * clamp(ubuf.contactRippleEnabled, 0.0, 1.0));
    vec3 reprojectedSceneDelta = forwardScene - surfaceColor.rgb;
    float reprojectedPeak = max(
        max(abs(reprojectedSceneDelta.r), abs(reprojectedSceneDelta.g)),
        abs(reprojectedSceneDelta.b)
    );
    const float refractionBudget = 36.0 / 255.0;
    float refractionScale = min(
        1.0, refractionBudget / max(reprojectedPeak, 0.000001)
    );
    vec3 coherentRefraction = reprojectedSceneDelta
                            * refractionScale
                            * responseWeight;
    float refractionLuma = dot(
        coherentRefraction, vec3(0.2126, 0.7152, 0.0722)
    );
    coherentRefraction *= mix(0.20, 1.0, step(0.0, refractionLuma));
    float neutralHighlight = mix(
        6.0 / 255.0, 40.0 / 255.0, pow(materialVariation, 1.05)
    ) * responseWeight;
    vec3 weightedSceneDelta = coherentRefraction + vec3(neutralHighlight);

    // One scalar protects both the bounded optical contrast and RGB gamut.
    // The same scale applies to the coherent scene sample and neutral water
    // highlight, so the result cannot form a black or opponent-color band.
    const float maximumContrast = 48.0 / 255.0;
    float weightedDeltaPeak = max(
        max(abs(weightedSceneDelta.r), abs(weightedSceneDelta.g)),
        abs(weightedSceneDelta.b)
    );
    float contrastScale = min(
        1.0, maximumContrast / max(weightedDeltaPeak, 0.000001)
    );
    vec3 positiveRoom = (vec3(1.0) - surfaceColor.rgb)
                      / max(weightedSceneDelta, vec3(0.000001));
    vec3 negativeRoom = surfaceColor.rgb
                      / max(-weightedSceneDelta, vec3(0.000001));
    vec3 channelGamutScale = mix(
        negativeRoom,
        positiveRoom,
        step(vec3(0.0), weightedSceneDelta)
    );
    float gamutScale = min(
        1.0,
        min(channelGamutScale.r,
            min(channelGamutScale.g, channelGamutScale.b))
    );
    float sharedGamutScale = min(contrastScale, gamutScale);
    surfaceColor.rgb = surfaceColor.rgb
                     + weightedSceneDelta * sharedGamutScale;
    fragColor = vec4(surfaceColor.rgb, 1.0) * ubuf.qt_Opacity;
}
