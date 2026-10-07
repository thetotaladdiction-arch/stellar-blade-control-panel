#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float wetIntensity;
    float surfaceAspect;
    vec2 viewportSize;
    float rippleDisplacementPixels;
    float sceneTime;
    float sceneWind;
    float waterEnergy;
    vec4 ripple0;
    vec4 ripple1;
    vec4 ripple2;
    vec4 ripple3;
    vec4 ripple4;
    vec4 ripple5;
    vec4 ripple6;
    vec4 ripple7;
    vec4 lens0;
    vec4 lens1;
    vec4 lens2;
    vec4 lens3;
    vec4 lens4;
    vec4 lens5;
    vec4 lens6;
    vec4 lens7;
} ubuf;

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D wetMask;
layout(binding = 3) uniform sampler2D wetNormal;

vec2 persistentWetNormal(vec2 uv, out float microHighlight)
{
    vec2 windDirection = normalize(vec2(0.22 + ubuf.sceneWind * 0.90, 1.0));
    vec2 uvA = fract(uv * 1.70 + windDirection * ubuf.sceneTime * 0.0060);
    vec2 uvB = fract(vec2(1.0 - uv.x, uv.y) * 2.30
                     - windDirection.yx * ubuf.sceneTime * 0.0042);
    vec2 normalA = texture(wetNormal, uvA).rg * 2.0 - 1.0;
    vec2 normalB = texture(wetNormal, uvB).gr * 2.0 - 1.0;
    vec2 combined = (normalA + normalB * 0.62) * 0.58;
    microHighlight = smoothstep(0.20, 0.88,
                                abs(combined.x * 0.68 + combined.y * 0.32));
    return combined;
}

float brokenBand(vec2 uv, float angle, float seed)
{
    float coarse = sin(angle * (9.0 + seed * 2.0) + seed * 6.17);
    float fine = sin(angle * (23.0 + seed * 3.0) - seed * 4.31);
    float roughness = texture(wetNormal, clamp(uv, vec2(0.0), vec2(1.0))).r * 2.0 - 1.0;
    return smoothstep(-0.58, 0.26, coarse * 0.52 + fine * 0.24 + roughness * 0.38);
}

void accumulateRing(
    float distanceFromImpact,
    float front,
    float width,
    float polarity,
    float breakage,
    float strength,
    vec2 direction,
    inout vec2 displacement,
    inout float crest
)
{
    float signedDistance = distanceFromImpact - front;
    float envelope = exp(-(signedDistance * signedDistance) / max(width * width, 0.000001));
    float response = envelope * polarity * mix(0.06, 1.0, breakage) * strength;
    displacement += direction * response;
    crest += abs(response);
}

void accumulateRipple(
    vec4 ripple,
    vec2 uv,
    inout vec2 displacement,
    inout float crest
)
{
    float age = max(ripple.z, 0.0);
    float energy = max(ripple.w, 0.0);
    if (energy <= 0.0001 || age > 2.05) {
        return;
    }

    float aspect = max(ubuf.surfaceAspect, 0.001);
    float floorPerspective = mix(0.30, 0.58,
                                 smoothstep(0.48, 0.96, ripple.y));
    vec2 metricDelta = vec2((uv.x - ripple.x) * aspect,
                            (uv.y - ripple.y) / floorPerspective);
    float distanceFromImpact = length(metricDelta);
    vec2 metricDirection = metricDelta / max(distanceFromImpact, 0.0001);
    vec2 uvDirection = normalize(vec2(metricDirection.x / aspect,
                                      metricDirection.y * floorPerspective));
    float angle = atan(metricDelta.y, metricDelta.x);

    // Twenty-to-forty pixel contact rings expand to roughly 140-280px at
    // 960-wide over 1-1.6 seconds. Alternating fronts create broken bright
    // and dark pressure bands instead of a perfect HUD ellipse.
    float waveFront = 0.022 + age * 0.155;
    float fade = energy * exp(-age * 0.72);
    float broken0 = brokenBand(uv, angle, 0.7 + ripple.x * 3.0);
    float broken1 = brokenBand(uv.yx, angle, 1.9 + ripple.y * 4.0);
    float broken2 = brokenBand(vec2(1.0) - uv, angle, 3.1 + ripple.x * 2.0);
    accumulateRing(distanceFromImpact, waveFront - 0.012, 0.0046,
                   0.58, broken0, fade, uvDirection, displacement, crest);
    accumulateRing(distanceFromImpact, waveFront, 0.0032,
                   -1.0, broken1, fade, uvDirection, displacement, crest);
    accumulateRing(distanceFromImpact, waveFront + 0.013, 0.0040,
                   0.72, broken2, fade, uvDirection, displacement, crest);
}

void accumulateLens(
    vec4 lens,
    vec2 uv,
    inout vec2 lensDisplacement,
    inout float lensHighlight
)
{
    if (lens.w <= 0.0001 || lens.z <= 0.0001) {
        return;
    }
    float aspect = max(ubuf.surfaceAspect, 0.001);
    vec2 metricDelta = vec2((uv.x - lens.x) * aspect, uv.y - lens.y);
    vec2 local = metricDelta / lens.z;
    // A slight lower bulge gives the refraction a gravity-shaped lens rather
    // than a uniform circular blur pasted over the source.
    local.y += 0.18 * (1.0 - clamp(local.y * local.y, 0.0, 1.0));
    float radiusSquared = dot(local, local);
    if (radiusSquared >= 1.0) {
        return;
    }
    float body = smoothstep(1.0, 0.70, radiusSquared);
    float rim = exp(-abs(sqrt(max(radiusSquared, 0.0001)) - 0.82) * 34.0);
    vec2 direction = normalize(local + vec2(0.0001));
    vec2 uvDirection = vec2(direction.x / aspect, direction.y);
    float curvedSurface = sqrt(max(0.0, 1.0 - radiusSquared));
    lensDisplacement += uvDirection * curvedSurface * body * lens.w * 0.84;
    lensHighlight += (rim * 0.70 + body * 0.08) * lens.w;
}

void main()
{
    vec2 uv = qt_TexCoord0;
    float wet = clamp(texture(wetMask, uv).r, 0.0, 1.0);

    vec2 displacement = vec2(0.0);
    float crest = 0.0;
    accumulateRipple(ubuf.ripple0, uv, displacement, crest);
    accumulateRipple(ubuf.ripple1, uv, displacement, crest);
    accumulateRipple(ubuf.ripple2, uv, displacement, crest);
    accumulateRipple(ubuf.ripple3, uv, displacement, crest);
    accumulateRipple(ubuf.ripple4, uv, displacement, crest);
    accumulateRipple(ubuf.ripple5, uv, displacement, crest);
    accumulateRipple(ubuf.ripple6, uv, displacement, crest);
    accumulateRipple(ubuf.ripple7, uv, displacement, crest);

    vec2 lensDisplacement = vec2(0.0);
    float lensHighlight = 0.0;
    accumulateLens(ubuf.lens0, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens1, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens2, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens3, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens4, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens5, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens6, uv, lensDisplacement, lensHighlight);
    accumulateLens(ubuf.lens7, uv, lensDisplacement, lensHighlight);

    float responseStrength = clamp(ubuf.wetIntensity, 0.0, 1.0) * wet;
    float waterResponse = 1.0 - exp(-max(ubuf.waterEnergy, 0.0) * 0.035);
    float microHighlight = 0.0;
    vec2 flowingNormal = persistentWetNormal(uv, microHighlight);
    vec2 normalVector = texture(wetNormal, uv).rg * 2.0 - 1.0;
    vec2 pixelSize = 1.0 / max(ubuf.viewportSize, vec2(1.0));
    vec2 warpedUv = clamp(
        uv + (displacement * responseStrength
              + normalVector * min(crest, 1.0) * 0.18 * responseStrength
              + flowingNormal * (0.10 + waterResponse * 0.10) * responseStrength
              + lensDisplacement)
             * ubuf.rippleDisplacementPixels * pixelSize,
        vec2(0.0),
        vec2(1.0)
    );
    vec4 color = texture(source, warpedUv);

    float crestLight = min(crest, 1.4) * responseStrength;
    color.rgb += vec3(0.48, 0.69, 0.84) * crestLight * 0.045;
    color.rgb += vec3(0.52, 0.76, 0.92) * min(lensHighlight, 1.0) * 0.055;
    color.rgb += vec3(0.34, 0.58, 0.74) * microHighlight * responseStrength
                 * (0.010 + waterResponse * 0.010);
    color.rgb -= vec3(0.018, 0.012, 0.006) * responseStrength
                 * smoothstep(0.12, 0.80, crestLight);

    fragColor = color * ubuf.qt_Opacity;
}
