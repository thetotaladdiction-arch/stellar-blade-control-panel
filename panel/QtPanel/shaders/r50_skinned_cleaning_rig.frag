#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 1) in vec2 sceneCoord;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 rigSize;
    vec2 nativeSize;
    vec2 shoulderPivot;
    vec2 elbowPivot;
    vec2 wristPivot;
    vec2 gloveContactPivot;
    float shoulderAngle;
    float elbowAngle;
    float wristAngle;
    float forearmStretch;
    float gloveBendRadians;
    float upperArmFlexNativePx;
    float delayedClothTipAngle;
} ubuf;

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D weights;
layout(binding = 4) uniform sampler2D protectedSword;
layout(binding = 5) uniform sampler2D approvedSource;
layout(binding = 6) uniform sampler2D cleanplateSource;
layout(binding = 7) uniform sampler2D cleanplateMask;

vec2 cleanplateUv(vec2 sourceUv)
{
    vec2 sourcePx = sourceUv * vec2(3840.0, 2160.0);
    return (sourcePx - vec2(1408.0, 240.0)) / vec2(1232.0, 1136.0);
}

float feasibleCoverage(vec3 compositeColor, vec3 cleanplateColor)
{
    const float epsilon = 1.0e-6;
    vec3 brighter = max(compositeColor - cleanplateColor, vec3(0.0))
                  / max(vec3(1.0) - cleanplateColor, vec3(epsilon));
    vec3 darker = max(cleanplateColor - compositeColor, vec3(0.0))
                / max(cleanplateColor, vec3(epsilon));
    vec3 required = max(brighter, darker);
    return clamp(max(required.r, max(required.g, required.b)), 0.0, 1.0);
}

float protectedSwordGuard(vec2 uv)
{
    vec2 guardTexel = vec2(8.0 / 3840.0, 8.0 / 2160.0);
    float authority = 0.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            authority = max(authority, texture(
                protectedSword, uv + vec2(x, y) * guardTexel).r);
        }
    }
    return step(0.5 / 255.0, authority);
}

void main()
{
    vec4 sourceSample = texture(source, qt_TexCoord0);
    vec3 compositeColor = texture(approvedSource, qt_TexCoord0).rgb;
    vec3 cleanplateColor = texture(
        cleanplateSource, cleanplateUv(qt_TexCoord0)).rgb;
    float literalMoverCore = step(
        254.5 / 255.0,
        texture(cleanplateMask, cleanplateUv(qt_TexCoord0)).r);
    vec3 actualBackground = mix(
        compositeColor, cleanplateColor, literalMoverCore);
    vec3 rigidWeights = texture(weights, qt_TexCoord0).rgb;
    float deformingOwner = step(
        0.5 / 255.0, dot(rigidWeights, vec3(1.0)));
    float alphaOwner = step(5.5 / 255.0, sourceSample.a);
    float protectedOwner = protectedSwordGuard(sceneCoord);
    float effectiveAlpha = max(sourceSample.a, feasibleCoverage(
        compositeColor, actualBackground));
    vec3 foregroundPremultiplied = compositeColor
        - actualBackground * (1.0 - effectiveAlpha);
    foregroundPremultiplied = clamp(
        foregroundPremultiplied, vec3(0.0), vec3(effectiveAlpha));
    fragColor = vec4(foregroundPremultiplied, effectiveAlpha)
              * deformingOwner * alphaOwner
              * (1.0 - protectedOwner)
              * ubuf.qt_Opacity;
}
