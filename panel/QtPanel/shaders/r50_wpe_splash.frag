#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

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
    vec2 atlasSize;
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
layout(binding = 4) uniform sampler2D splashAtlas;
layout(binding = 5) uniform sampler2D splashNormalAtlas;

const float impactFrameCount = 24.0;
const vec2 impactAnchor = vec2(0.5, 0.72);

float seedUnit(float salt)
{
    return fract(sin((ubuf.eventSeed + salt) * 12.9898) * 43758.5453);
}

float serviceJetMask(vec2 sceneUv, vec4 jet)
{
    float activeGate = step(0.5, jet.w) * step(0.000001, jet.z);
    float radiusPixels = max(jet.z * ubuf.viewportSize.x, 0.0001);
    vec2 offsetPixels = (sceneUv - jet.xy) * ubuf.viewportSize;
    float radialDistance = length(offsetPixels) / radiusPixels;
    return (1.0 - smoothstep(0.42, 1.0, radialDistance)) * activeGate;
}

vec4 sampleImpactCell(float cell, vec2 localUv)
{
    vec2 atlasDimensions = max(ubuf.atlasSize, vec2(1.0));
    vec2 cellDimensions = vec2(
        atlasDimensions.x / impactFrameCount, atlasDimensions.y
    );
    vec2 cellTexel = 1.0 / cellDimensions;
    vec2 boundedUv = clamp(
        localUv, cellTexel * 1.5, vec2(1.0) - cellTexel * 1.5
    );
    vec2 sampleUv = vec2(
        (clamp(cell, 0.0, impactFrameCount - 1.0) + boundedUv.x)
            / impactFrameCount,
        boundedUv.y
    );
    float edgeFade = smoothstep(0.0, cellTexel.x * 2.0, localUv.x)
                   * (1.0 - smoothstep(
                       1.0 - cellTexel.x * 2.0, 1.0, localUv.x
                   ))
                   * smoothstep(0.0, cellTexel.y * 2.0, localUv.y)
                   * (1.0 - smoothstep(
                       1.0 - cellTexel.y * 2.0, 1.0, localUv.y
                   ));
    return textureLod(splashAtlas, sampleUv, 0.0) * edgeFade;
}

vec4 sampleImpactNormalCell(float cell, vec2 localUv)
{
    vec2 atlasDimensions = max(ubuf.atlasSize, vec2(1.0));
    vec2 cellDimensions = vec2(
        atlasDimensions.x / impactFrameCount, atlasDimensions.y
    );
    vec2 cellTexel = 1.0 / cellDimensions;
    vec2 boundedUv = clamp(
        localUv, cellTexel * 1.5, vec2(1.0) - cellTexel * 1.5
    );
    vec2 sampleUv = vec2(
        (clamp(cell, 0.0, impactFrameCount - 1.0) + boundedUv.x)
            / impactFrameCount,
        boundedUv.y
    );
    float edgeFade = smoothstep(0.0, cellTexel.x * 2.0, localUv.x)
                   * (1.0 - smoothstep(
                       1.0 - cellTexel.x * 2.0, 1.0, localUv.x
                   ))
                   * smoothstep(0.0, cellTexel.y * 2.0, localUv.y)
                   * (1.0 - smoothstep(
                       1.0 - cellTexel.y * 2.0, 1.0, localUv.y
                   ));
    vec4 authored = textureLod(splashNormalAtlas, sampleUv, 0.0);
    return vec4(
        mix(vec3(0.5, 0.5, 1.0), authored.rgb, edgeFade),
        authored.a * edgeFade
    );
}

void main()
{
    vec2 globalUv = ubuf.splashCenter
                  + (qt_TexCoord0 - impactAnchor) * ubuf.splashExtent;
    vec2 boundedGlobalUv = clamp(globalUv, vec2(0.0), vec2(1.0));

    vec4 centerReceiverMap = texture(
        surfaceResponse, clamp(ubuf.splashCenter, vec2(0.0), vec2(1.0))
    );
    float centerKeepout = texture(
        keepoutMask, clamp(ubuf.splashCenter, vec2(0.0), vec2(1.0))
    ).r;
    float centerReceiver = smoothstep(
        0.04, 0.28, min(centerReceiverMap.g, centerReceiverMap.a)
    ) * (1.0 - centerKeepout);

    vec2 crownFootUv = clamp(
        vec2(globalUv.x, ubuf.splashCenter.y), vec2(0.0), vec2(1.0)
    );
    vec4 crownFootReceiverMap = texture(surfaceResponse, crownFootUv);
    float crownFootKeepout = texture(keepoutMask, crownFootUv).r;
    float crownFootReceiver = smoothstep(
        0.04, 0.28, min(crownFootReceiverMap.g, crownFootReceiverMap.a)
    ) * (1.0 - crownFootKeepout);
    float localCrownKeepout = texture(keepoutMask, boundedGlobalUv).r;
    float groundProximity = smoothstep(0.62, 0.76, qt_TexCoord0.y);
    float crownFootGate = mix(1.0, crownFootReceiver, groundProximity);
    float crownGate = centerReceiver * crownFootGate
                    * (1.0 - localCrownKeepout);
    if (crownGate <= 0.001) {
        fragColor = vec4(0.0);
        return;
    }

    float eventStrength = clamp(ubuf.strength, 0.0, 1.0);
    float energy = sqrt(eventStrength);
    float normalizedImpactAge = clamp(
        ubuf.age / max(ubuf.lifetime, 0.0001), 0.0, 1.0
    );
    float impactFramePosition = normalizedImpactAge
                              * (impactFrameCount - 1.0);
    float impactFrame = floor(impactFramePosition);
    float nextImpactFrame = min(impactFrame + 1.0, impactFrameCount - 1.0);
    float impactFrameBlend = fract(impactFramePosition);

    bool mirrored = seedUnit(2.7) >= 0.5;
    float seedScaleX = mix(0.96, 1.04, seedUnit(4.3));
    float seedScaleY = mix(0.97, 1.03, seedUnit(6.1));
    vec2 localAtlasUv = (
        qt_TexCoord0 - impactAnchor
    ) / vec2(seedScaleX, seedScaleY) + impactAnchor;
    if (mirrored) {
        localAtlasUv.x = 1.0 - localAtlasUv.x;
    }

    vec4 atlasSampleA = sampleImpactCell(impactFrame, localAtlasUv);
    vec4 atlasSampleB = sampleImpactCell(nextImpactFrame, localAtlasUv);
    vec4 atlasSample = mix(atlasSampleA, atlasSampleB, impactFrameBlend);
    vec4 normalSampleA = sampleImpactNormalCell(impactFrame, localAtlasUv);
    vec4 normalSampleB = sampleImpactNormalCell(
        nextImpactFrame, localAtlasUv
    );
    vec4 normalSample = mix(
        normalSampleA, normalSampleB, impactFrameBlend
    );

    // Match WPE genericparticle: Texture0 supplies its complete authored RGBA.
    // This atlas is premultiplied, so atlasSample.rgb already contains coverage
    // and must not be multiplied by spriteAlpha again below.
    float localAtlasOwnedSupport = clamp(atlasSample.a, 0.0, 1.0);
    float fringeGuard = smoothstep(0.004, 0.018, localAtlasOwnedSupport);
    float atlasSafeAlpha = localAtlasOwnedSupport * fringeGuard;
    float authoredNormalWeight = clamp(normalSample.a, 0.0, 1.0)
                               * fringeGuard;
    vec3 decodedNormal = normalize(normalSample.rgb * 2.0 - 1.0);
    if (mirrored) {
        decodedNormal.x = -decodedNormal.x;
    }
    decodedNormal.xy *= vec2(seedScaleX, seedScaleY);
    decodedNormal = normalize(decodedNormal);

    vec3 sceneColor = texture(sceneSource, boundedGlobalUv).rgb;
    const float wpeRefractionAmount = 0.05;
    vec2 refractionOffset = vec2(decodedNormal.x, -decodedNormal.y)
                          * wpeRefractionAmount
                          * authoredNormalWeight * energy;
    vec3 refractedScene = texture(
        sceneSource,
        clamp(boundedGlobalUv + refractionOffset, vec2(0.0), vec2(1.0))
    ).rgb;
    // Midpoint of the official water_impact particle color range. The scene
    // still owns spatial hue because WPE multiplies this tint by the displaced
    // framebuffer sample.
    vec3 officialWaterTint = vec3(206.0, 215.5, 255.0) / 255.0;
    vec3 crownPremultiplied = refractedScene * officialWaterTint * atlasSample.rgb
                            * fringeGuard * energy * crownGate;

    float spriteAlpha = atlasSafeAlpha * energy;
    spriteAlpha *= crownGate;

    float dropletMask = 0.0;
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet0));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet1));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet2));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet3));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet4));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet5));
    dropletMask = max(dropletMask, serviceJetMask(globalUv, ubuf.jet6));
    float jetFade = 1.0 - smoothstep(0.52, 0.70, ubuf.age);
    dropletMask *= jetFade * centerReceiver * (1.0 - localCrownKeepout);
    vec2 dropletDirection = globalUv - ubuf.splashCenter;
    float dropletDistance = length(dropletDirection * ubuf.viewportSize);
    dropletDirection /= max(dropletDistance, 0.0001);
    vec3 dropletRefractedScene = texture(
        sceneSource,
        clamp(
            boundedGlobalUv + dropletDirection * 1.25
                / max(ubuf.viewportSize, vec2(1.0)),
            vec2(0.0), vec2(1.0)
        )
    ).rgb;
    vec3 dropletColor = dropletRefractedScene * officialWaterTint;
    float dropletAlpha = dropletMask * energy * 0.58;

    vec3 premultiplied = dropletColor * dropletAlpha;
    float alpha = dropletAlpha;
    premultiplied = crownPremultiplied
                  + premultiplied * (1.0 - spriteAlpha);
    alpha = spriteAlpha + alpha * (1.0 - spriteAlpha);

    premultiplied = clamp(premultiplied, vec3(0.0), vec3(alpha));
    fragColor = vec4(premultiplied, alpha) * ubuf.qt_Opacity;
}
