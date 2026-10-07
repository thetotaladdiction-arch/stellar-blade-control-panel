#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 1) in vec2 qt_SceneCoord;
layout(location = 0) out vec4 fragColor;

// Keep this block byte-for-byte identical to the vertex stage. Each jet is
// packed as scene x, scene y, scene-normalized radius, validity.
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float age;
    float lifetime;
    float strength;
    float eventSeed;
    float roleCode;
    vec2 splashCenter;
    vec2 splashExtent;
    vec2 viewportSize;
    float sceneTime;
    float waterRippleSpeed;
    vec4 jet0;
    vec4 jet1;
    vec4 jet2;
    vec4 jet3;
    vec4 jet4;
    vec4 jet5;
    vec4 jet6;
} ubuf;

layout(binding = 1) uniform sampler2D surfaceResponse;
layout(binding = 2) uniform sampler2D keepoutMask;
layout(binding = 3) uniform sampler2D sceneSource;
layout(binding = 4) uniform sampler2D waterRippleNormal;

float saturate(float value)
{
    return clamp(value, 0.0, 1.0);
}

float eventVariation(float salt)
{
    return fract(sin((ubuf.eventSeed + salt) * 12.9898) * 43758.5453);
}

vec2 sceneToPixels(vec2 scenePosition)
{
    return scenePosition * max(ubuf.viewportSize, vec2(1.0));
}

float segmentCoverage(vec2 point, vec2 start, vec2 end, float radius)
{
    vec2 segment = end - start;
    float denominator = max(dot(segment, segment), 0.0001);
    float along = clamp(dot(point - start, segment) / denominator, 0.0, 1.0);
    float distancePixels = length(point - (start + segment * along));
    return 1.0 - smoothstep(max(0.2, radius - 0.8), radius + 0.8,
                            distancePixels);
}

vec2 distributedFloorAnchor(int index)
{
    float fraction = float(index) / 6.0;
    float seedBend = eventVariation(41.0 + float(index) * 3.0);
    return ubuf.splashCenter + vec2(
        (fraction - 0.5) * ubuf.splashExtent.x * 0.18,
        ubuf.splashExtent.y * (0.006 + seedBend * 0.012)
    );
}

float quadraticBezierTube(
    vec2 point,
    vec2 start,
    vec2 control,
    vec2 end,
    float radiusPixels,
    out float bestAlong
)
{
    float minimumDistance = 1000000.0;
    bestAlong = 0.0;
    vec2 previous = start;
    for (int segmentIndex = 1; segmentIndex <= 6; ++segmentIndex) {
        float curveAlong = float(segmentIndex) / 6.0;
        float inverseAlong = 1.0 - curveAlong;
        vec2 current = inverseAlong * inverseAlong * start
                     + 2.0 * inverseAlong * curveAlong * control
                     + curveAlong * curveAlong * end;
        vec2 edge = current - previous;
        float edgeDenominator = max(dot(edge, edge), 0.0001);
        float edgeAlong = clamp(
            dot(point - previous, edge) / edgeDenominator, 0.0, 1.0
        );
        float distancePixels = length(
            point - (previous + edge * edgeAlong)
        );
        if (distancePixels < minimumDistance) {
            minimumDistance = distancePixels;
            bestAlong = (float(segmentIndex - 1) + edgeAlong) / 6.0;
        }
        previous = current;
    }
    return 1.0 - smoothstep(
        max(0.2, radiusPixels - 0.8), radiusPixels + 0.8,
        minimumDistance
    );
}

vec2 crownCurveControl(vec2 start, vec2 end, int index)
{
    float seededBend = eventVariation(61.0 + float(index) * 11.0);
    float side = sign(float(index) - 3.0);
    if (index == 3) {
        side = mix(-1.0, 1.0, step(0.5, seededBend));
    }
    float risePixels = max(start.y - end.y, 8.0);
    float outwardBend = side * (4.0 + seededBend * 8.0);
    return mix(start, end, 0.46)
         + vec2(outwardBend, -risePixels * (0.09 + seededBend * 0.05));
}

float curvedConcaveLobe(
    vec2 point,
    vec2 floorAnchor,
    vec4 jet,
    float openingStage,
    float tearStage,
    float lateTearStage,
    int index
)
{
    float validity = step(0.5, jet.w);
    vec2 start = sceneToPixels(floorAnchor);
    vec2 end = sceneToPixels(jet.xy);
    vec2 control = crownCurveControl(start, end, index);
    float radiusPixels = clamp(
        jet.z * ubuf.viewportSize.x * 2.55, 3.2, 6.2
    );
    float curveAlong = 0.0;
    float outerBlade = quadraticBezierTube(
        point, start, control, end, radiusPixels, curveAlong
    );

    float seededTearBias = eventVariation(109.0 + float(index) * 7.0);
    float inverseAlong = 1.0 - curveAlong;
    vec2 curvePoint = inverseAlong * inverseAlong * start
                    + 2.0 * inverseAlong * curveAlong * control
                    + curveAlong * curveAlong * end;
    vec2 gapDirection = normalize(
        vec2(ubuf.splashCenter.x, jet.y) * ubuf.viewportSize
        - curvePoint + vec2(0.0001)
    );
    vec2 gapCenter = curvePoint + gapDirection
                   * radiusPixels * (0.42 + seededTearBias * 0.18);
    float gapDistance = length(point - gapCenter);
    float openNegativeGap = (1.0 - smoothstep(
        radiusPixels * 0.18,
        radiusPixels * (0.50 + seededTearBias * 0.10),
        gapDistance
    )) * smoothstep(0.20, 0.48, curveAlong)
       * (1.0 - smoothstep(0.82, 0.98, curveAlong));

    float lateTopologyBreakup = smoothstep(
        0.20, 0.92,
        lateTearStage * (0.72 + seededTearBias * 0.42)
        + curveAlong * 0.18
    );
    float lobeSurvival = 1.0 - lateTopologyBreakup
                       * step(0.44, seededTearBias) * 0.78;
    float breakupWave = 0.5 + 0.5 * sin(
        curveAlong * 23.0 + float(index) * 2.41
        + ubuf.eventSeed * 0.37
    );
    lobeSurvival *= 1.0 - tearStage
                  * smoothstep(0.76, 0.96, breakupWave)
                  * smoothstep(0.36, 0.84, curveAlong) * 0.56;
    float concaveBlade = max(
        0.0, outerBlade - openNegativeGap * (0.68 + tearStage * 0.24)
    );
    float rootTaper = smoothstep(0.0, 0.10, curveAlong);
    float tipTaper = 1.0 - 0.22 * smoothstep(0.84, 1.0, curveAlong);
    return validity * concaveBlade * lobeSurvival
           * rootTaper * tipTaper * openingStage;
}

float fragmentedFoamRim(
    vec2 point,
    vec2 floorAnchor,
    vec4 jet,
    float rimLife,
    float lateTearStage,
    int index
)
{
    float validity = step(0.5, jet.w);
    vec2 start = sceneToPixels(floorAnchor);
    vec2 end = sceneToPixels(jet.xy);
    vec2 control = crownCurveControl(start, end, index);
    float curveAlong = 0.0;
    float rimTube = quadraticBezierTube(
        point, start, control, end,
        1.15 + eventVariation(137.0 + float(index) * 5.0) * 0.85,
        curveAlong
    );
    float seededTearBias = eventVariation(109.0 + float(index) * 7.0);
    float fragmentPhase = fract(
        curveAlong * (4.0 + seededTearBias * 2.0)
        + seededTearBias * 1.7 + lateTearStage * 0.74
    );
    float foamFragmentMask = smoothstep(0.10, 0.24, fragmentPhase)
                           * (1.0 - smoothstep(0.70, 0.88, fragmentPhase));
    float upperRim = smoothstep(0.34, 0.58, curveAlong);
    float tipFoam = smoothstep(0.80, 0.94, curveAlong);
    float lateTopologyBreakup = smoothstep(
        0.30, 0.94, lateTearStage * (0.70 + seededTearBias * 0.48)
    );
    float lobeSurvival = 1.0 - lateTopologyBreakup
                       * step(0.54, seededTearBias) * 0.62;
    return validity * rimLife * rimTube * upperRim * lobeSurvival
           * max(foamFragmentMask, tipFoam);
}

float contactCompression(vec2 point, float openingStage)
{
    vec2 centerPixels = sceneToPixels(ubuf.splashCenter);
    vec2 fullExtentPixels = max(
        sceneToPixels(ubuf.splashExtent), vec2(2.0)
    );
    vec2 compressionHalfSize = vec2(
        clamp(fullExtentPixels.x * 0.065, 6.0, 12.0),
        clamp(fullExtentPixels.y * 0.018, 1.0, 2.0)
    );
    vec2 compressionMetric = (point - centerPixels)
                           / compressionHalfSize;
    float footprint = 1.0 - smoothstep(0.48, 1.0, length(compressionMetric));
    return footprint * (1.0 - openingStage * 0.78);
}

vec4 clampJetToRasterBounds(vec4 jet)
{
    vec2 cardSceneMinimum = ubuf.splashCenter
                          + vec2(-0.5, -0.72) * ubuf.splashExtent;
    vec2 cardSceneMaximum = ubuf.splashCenter
                          + vec2(0.5, 0.28) * ubuf.splashExtent;
    jet.xy = clamp(jet.xy, cardSceneMinimum, cardSceneMaximum);
    return jet;
}

float curvedJetStream(
    vec2 point,
    vec2 floorAnchor,
    vec4 jet,
    float life,
    int index
)
{
    float validity = step(0.5, jet.w);
    vec2 start = sceneToPixels(floorAnchor);
    vec2 end = sceneToPixels(jet.xy);
    vec2 control = crownCurveControl(start, end, index);
    float curveAlong = 0.0;
    float sparseSelector = step(
        0.34, eventVariation(167.0 + float(index) * 13.0)
    );
    float streamTube = quadraticBezierTube(
        point, start, control, end,
        max(0.72, jet.z * ubuf.viewportSize.x * 0.56), curveAlong
    );
    float upperStream = smoothstep(0.46, 0.62, curveAlong);
    float threadBreak = 0.76 + 0.24 * sin(
        curveAlong * 19.0 + ubuf.eventSeed + float(index) * 1.9
    );
    return validity * sparseSelector * life * streamTube
           * upperStream * threadBreak;
}

float detachedBead(vec2 point, vec4 jet, float life, int index)
{
    float validity = step(0.5, jet.w);
    float direction = eventVariation(73.0 + float(index) * 5.0) - 0.5;
    float radiusPixels = max(0.8, jet.z * ubuf.viewportSize.x * 0.72);
    vec2 beadCenter = sceneToPixels(jet.xy)
                    + vec2(direction * radiusPixels * 2.2,
                           -radiusPixels * (1.25 + 0.18 * float(index % 3)));
    float bead = 1.0 - smoothstep(
        radiusPixels * 0.58,
        radiusPixels,
        length(point - beadCenter)
    );
    return validity * life * bead;
}

vec2 sampleWpeWaterNormal(vec2 sceneUv)
{
    float phase = ubuf.sceneTime * ubuf.waterRippleSpeed;
    vec2 normalA = texture(
        waterRippleNormal,
        fract(sceneUv * vec2(4.1, 3.7) + vec2(phase * 0.031, phase * 0.019))
    ).rg * 2.0 - 1.0;
    vec2 normalB = texture(
        waterRippleNormal,
        fract(sceneUv.yx * vec2(3.2, 4.4) + vec2(-phase * 0.017, phase * 0.027))
    ).gr * 2.0 - 1.0;
    return (normalA + normalB * 0.64) / 1.64;
}

vec3 analyticCrownProfileNormal(vec2 sceneUv, float openingStage)
{
    vec2 minimumExtent = 1.0 / max(ubuf.viewportSize, vec2(1.0));
    vec2 crownLocal = (sceneUv - ubuf.splashCenter)
                    / max(ubuf.splashExtent, minimumExtent);
    float normalizedCrownX = clamp(crownLocal.x / 0.5, -1.0, 1.0);
    float crownHeightProfile = max(
        0.0, 1.0 - normalizedCrownX * normalizedCrownX
    );
    float crownProfileSlope = -2.0 * normalizedCrownX;
    float crownRise = saturate(-crownLocal.y / 0.72);
    float verticalProfileSlope = mix(-0.28, 0.42, crownRise)
                               * mix(0.78, 1.0, openingStage);
    return normalize(vec3(
        -crownProfileSlope * 0.42,
        -verticalProfileSlope * 0.36,
        1.0 + crownHeightProfile * 0.12
    ));
}

float conservativeKeepout(vec2 sceneUv)
{
    vec2 texel = 1.0 / max(ubuf.viewportSize, vec2(1.0));
    float keepoutAuthority = texture(keepoutMask, sceneUv).r;
    keepoutAuthority = max(keepoutAuthority,
        texture(keepoutMask, sceneUv + vec2(texel.x, 0.0)).r);
    keepoutAuthority = max(keepoutAuthority,
        texture(keepoutMask, sceneUv - vec2(texel.x, 0.0)).r);
    keepoutAuthority = max(keepoutAuthority,
        texture(keepoutMask, sceneUv + vec2(0.0, texel.y)).r);
    keepoutAuthority = max(keepoutAuthority,
        texture(keepoutMask, sceneUv - vec2(0.0, texel.y)).r);
    return keepoutAuthority;
}

void main()
{
    vec2 sceneUv = clamp(qt_SceneCoord, vec2(0.0), vec2(1.0));
    vec2 pointPixels = sceneToPixels(sceneUv);
    float progress = saturate(ubuf.age / max(ubuf.lifetime, 0.0001));
    float openingStage = smoothstep(0.015, 0.18, progress);
    float tearStage = smoothstep(0.38, 0.72, progress);
    float lateTearStage = smoothstep(0.62, 0.94, progress);
    float collapseStage = smoothstep(0.68, 1.0, progress);
    float sheetLife = openingStage * (1.0 - collapseStage);
    float rimLife = smoothstep(0.035, 0.14, progress)
                  * (1.0 - smoothstep(0.72, 0.98, progress));
    float streamLife = smoothstep(0.09, 0.24, progress)
                     * (1.0 - smoothstep(0.66, 0.94, progress));
    float beadLife = smoothstep(0.20, 0.42, progress)
                   * (1.0 - smoothstep(0.76, 1.0, progress));
    float roleScale = mix(0.84, 1.0, step(0.5, ubuf.roleCode));
    // The 480-wide QA mask was two rows short of the frozen splash support.
    // Evaluate the same analytic silhouette at +/-2 final pixels in Y only;
    // this is exactly +/-1 QA pixel and cannot widen the crown horizontally.
    const float silhouetteVerticalSupportPixels = 2.0;
    vec2 verticalSupportOffset = vec2(0.0, silhouetteVerticalSupportPixels);
    vec2 upperSupportPoint = pointPixels - verticalSupportOffset;
    vec2 lowerSupportPoint = pointPixels + verticalSupportOffset;

    vec4 jetStates[7] = vec4[7](
        clampJetToRasterBounds(ubuf.jet0),
        clampJetToRasterBounds(ubuf.jet1),
        clampJetToRasterBounds(ubuf.jet2),
        clampJetToRasterBounds(ubuf.jet3),
        clampJetToRasterBounds(ubuf.jet4),
        clampJetToRasterBounds(ubuf.jet5),
        clampJetToRasterBounds(ubuf.jet6)
    );
    float anyValid = 0.0;
    float bodyCoverage = 0.0;
    float foamCoverage = 0.0;
    float streamCoverage = 0.0;
    float beadCoverage = 0.0;
    for (int index = 0; index < 7; ++index) {
        anyValid = max(anyValid, jetStates[index].w);
        vec2 floorAnchor = distributedFloorAnchor(index);
        float lobeCoverage = curvedConcaveLobe(
            pointPixels, floorAnchor, jetStates[index],
            openingStage, tearStage, lateTearStage, index
        );
        lobeCoverage = max(lobeCoverage, curvedConcaveLobe(
            upperSupportPoint, floorAnchor, jetStates[index],
            openingStage, tearStage, lateTearStage, index
        ));
        lobeCoverage = max(lobeCoverage, curvedConcaveLobe(
            lowerSupportPoint, floorAnchor, jetStates[index],
            openingStage, tearStage, lateTearStage, index
        ));
        bodyCoverage = max(bodyCoverage, lobeCoverage);

        float lobeFoamCoverage = fragmentedFoamRim(
            pointPixels, floorAnchor, jetStates[index],
            rimLife, lateTearStage, index
        );
        lobeFoamCoverage = max(lobeFoamCoverage, fragmentedFoamRim(
            upperSupportPoint, floorAnchor, jetStates[index],
            rimLife, lateTearStage, index
        ));
        lobeFoamCoverage = max(lobeFoamCoverage, fragmentedFoamRim(
            lowerSupportPoint, floorAnchor, jetStates[index],
            rimLife, lateTearStage, index
        ));
        foamCoverage = max(foamCoverage, lobeFoamCoverage);

        float jetStreamCoverage = curvedJetStream(
            pointPixels, floorAnchor, jetStates[index], streamLife, index
        );
        streamCoverage = max(streamCoverage, jetStreamCoverage);
        float jetBeadCoverage = detachedBead(
            pointPixels, jetStates[index], beadLife * tearStage, index
        );
        beadCoverage = max(beadCoverage, jetBeadCoverage);
    }

    float compression = contactCompression(pointPixels, openingStage)
                      * (1.0 - smoothstep(0.18, 0.34, progress));
    float groundCoverage = compression;
    float airborneCoverage = max(bodyCoverage * sheetLife,
        max(foamCoverage, max(streamCoverage, beadCoverage)));
    float lineageGate = step(0.5, anyValid) * roleScale;
    groundCoverage *= lineageGate;
    airborneCoverage *= lineageGate;
    float silhouette = max(groundCoverage, airborneCoverage);
    if (silhouette <= 0.0001 || ubuf.strength <= 0.0) {
        fragColor = vec4(0.0);
        return;
    }

    vec4 response = texture(surfaceResponse, sceneUv);
    float wetAuthority = response.b * response.a;
    float localWetGate = smoothstep(0.02, 0.32, wetAuthority);
    vec4 contactFootResponse = texture(
        surfaceResponse, clamp(ubuf.splashCenter, vec2(0.0), vec2(1.0))
    );
    float contactWetAuthority = contactFootResponse.b * contactFootResponse.a;
    float contactWetGate = smoothstep(0.02, 0.32, contactWetAuthority);
    float keepoutAuthority = conservativeKeepout(sceneUv);
    float keepoutGate = 1.0 - step(0.58, keepoutAuthority);
    float authorizedSilhouette = max(
        groundCoverage * localWetGate,
        airborneCoverage * contactWetGate
    );
    authorizedSilhouette *= keepoutGate;
    if (authorizedSilhouette <= 0.0) {
        fragColor = vec4(0.0);
        return;
    }
    silhouette = authorizedSilhouette;

    vec2 eventNormalOffset = vec2(
        eventVariation(191.0), eventVariation(223.0)
    );
    vec2 wpeNormal = sampleWpeWaterNormal(sceneUv + eventNormalOffset);
    vec3 analyticCrownNormal = analyticCrownProfileNormal(
        sceneUv, openingStage
    );
    vec3 materialNormal = normalize(vec3(
        analyticCrownNormal.xy * 0.85 + wpeNormal * 0.15,
        max(analyticCrownNormal.z, 0.24)
    ));
    vec2 radialDirection = normalize(
        (sceneUv - ubuf.splashCenter) * ubuf.viewportSize + vec2(0.0001)
    );
    vec2 opticalDirection = normalize(materialNormal.xy * 0.78
                                    + radialDirection * 0.22
                                    + vec2(0.0001));
    const float maximumRefractionPixels = 3.0;
    const float maximumSampleDisplacementPixels = 3.0;
    const float maximumOutputAlpha = 0.88;
    const float maximumAdditiveResponse = 100.0 / 255.0;
    const float baseNeutralResponse = 28.0 / 255.0;
    const float rimNeutralResponse = 48.0 / 255.0;
    const float specularNeutralResponse = 26.0 / 255.0;
    float rawRefractionPixels = (1.25 + 4.25 * saturate(ubuf.strength))
                              * silhouette
                              * (1.0 - collapseStage * 0.42);
    float refractionPixels = clamp(rawRefractionPixels, 0.0, maximumRefractionPixels);
    refractionPixels = min(refractionPixels, maximumSampleDisplacementPixels);
    vec2 sampleDirectionUv = opticalDirection
                           / max(ubuf.viewportSize, vec2(1.0));
    vec2 refractionUv = sampleDirectionUv * refractionPixels;
    vec3 refractedScene = texture(
        sceneSource, clamp(sceneUv + refractionUv, vec2(0.0), vec2(1.0))
    ).rgb;
    float rimWeight = saturate(foamCoverage + beadCoverage * 0.72);
    vec3 viewDirection = vec3(0.0, 0.0, 1.0);
    vec3 localLightDirection = normalize(vec3(
        -radialDirection.x * 0.30,
        -radialDirection.y * 0.18,
        0.86
    ));
    vec3 halfwayDirection = normalize(viewDirection + localLightDirection);
    float fresnelResponse = saturate(
        pow(1.0 - saturate(materialNormal.z), 3.0) * 1.65
        + rimWeight * 0.58
    );
    float specularResponse = pow(max(dot(materialNormal, halfwayDirection), 0.0), 48.0);

    // WPE's decoded particle material is exact 255/255/255. Keep its additive
    // response neutral; scene hue exists only in the coherent refracted sample.
    const vec3 decodedParticleMaterialColor = vec3(1.0);
    const float bodyOpacity = 0.42;
    const float foamOpacity = 0.82;
    float lateOpticalFade = 1.0 - smoothstep(0.48, 0.86, progress);
    float crownOpacity = mix(bodyOpacity, foamOpacity, rimWeight);
    float alpha = silhouette * saturate(ubuf.strength)
                * crownOpacity;
    alpha *= lateOpticalFade;
    alpha = clamp(alpha, 0.0, maximumOutputAlpha);

    float rimResponse = max(rimWeight, fresnelResponse * 0.22);
    float lifecycleWeight = saturate(ubuf.strength) * lateOpticalFade;
    float unboundedNeutralAdditive = (
        baseNeutralResponse
        + rimNeutralResponse * rimResponse
        + specularNeutralResponse * specularResponse
    ) * silhouette * lifecycleWeight;
    float neutralAdditiveScalar = min(unboundedNeutralAdditive, maximumAdditiveResponse);
    vec3 neutralAdditivePremul = vec3(neutralAdditiveScalar)
                               * decodedParticleMaterialColor;
    fragColor = vec4(
        refractedScene * alpha + neutralAdditivePremul, alpha
    ) * ubuf.qt_Opacity;
}
