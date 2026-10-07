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
layout(binding = 4) uniform sampler2D currentOccupancy;
layout(binding = 5) uniform sampler2D originalOccupancy;

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
    float authoredDistance = texture(cleanplateMask, qt_TexCoord0).r;
    float collar = step(0.5 / 255.0, authoredDistance)
                 * (1.0 - step(254.5 / 255.0, authoredDistance));
    vec2 outputUv = sceneUv(qt_TexCoord0);
    float emptyHere = 1.0 - step(
        5.5 / 255.0, texture(currentOccupancy, outputUv).r);
    float protectedOwner = protectedSwordGuard(qt_TexCoord0);
    if (collar < 0.5 || emptyHere < 0.5 || protectedOwner > 0.5) {
        fragColor = vec4(0.0);
        return;
    }

    // Three 960-output pixels equal the authored 12-native-pixel collar. The
    // cached authority is already eroded by one output pixel, so this bounded
    // search is exactly original-interior minus current pose occupancy.
    float vacatedInterior = 0.0;
    for (int y = -3; y <= 3; ++y) {
        for (int x = -3; x <= 3; ++x) {
            vec2 offset = vec2(x, y) / vec2(960.0, 540.0);
            float originalInterior = step(249.5 / 255.0, texture(
                originalOccupancy, outputUv + offset).r);
            float currentInteriorEmpty = 1.0 - step(
                5.5 / 255.0,
                texture(currentOccupancy, outputUv + offset).r);
            vacatedInterior = max(
                vacatedInterior, originalInterior * currentInteriorEmpty);
        }
    }

    float reveal = authoredDistance * collar * emptyHere
                 * vacatedInterior * (1.0 - protectedOwner);
    vec4 cleanplate = texture(cleanplateSource, qt_TexCoord0);
    fragColor = vec4(cleanplate.rgb * reveal, reveal) * ubuf.qt_Opacity;
}
