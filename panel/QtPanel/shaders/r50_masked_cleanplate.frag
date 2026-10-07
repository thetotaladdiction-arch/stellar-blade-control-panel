#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
} ubuf;

layout(binding = 1) uniform sampler2D cleanplateSource;
layout(binding = 2) uniform sampler2D cleanplateMask;
layout(binding = 3) uniform sampler2D protectedSword;
layout(binding = 4) uniform sampler2D sourceAuthority;
layout(binding = 5) uniform sampler2D renderWeights;

vec2 sceneUv(vec2 cropUv)
{
    vec2 nativePx = vec2(1408.0, 240.0)
                  + cropUv * vec2(1232.0, 1136.0);
    return nativePx / vec2(3840.0, 2160.0);
}

float protectedSwordGuard(vec2 uv)
{
    vec2 guardTexel = vec2(8.0 / 1232.0, 8.0 / 1136.0);
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
    vec4 sourceColor = texture(cleanplateSource, qt_TexCoord0);
    float mask = texture(cleanplateMask, qt_TexCoord0).r;
    float literalMoverCore = step(254.5 / 255.0, mask);
    vec2 sourceUv = sceneUv(qt_TexCoord0);
    float alphaOwner = step(
        5.5 / 255.0, texture(sourceAuthority, sourceUv).a);
    vec3 rigidWeights = texture(renderWeights, sourceUv).rgb;
    float deformingOwner = step(
        0.5 / 255.0, dot(rigidWeights, vec3(1.0)));
    float protectedOwner = protectedSwordGuard(qt_TexCoord0);
    fragColor = sourceColor * literalMoverCore * alphaOwner * deformingOwner
              * (1.0 - protectedOwner)
              * ubuf.qt_Opacity;
}
