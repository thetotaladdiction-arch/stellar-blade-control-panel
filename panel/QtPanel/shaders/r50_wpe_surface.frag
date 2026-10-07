#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    float sceneTime;
    float waterRippleSpeed;
    float waterRippleStrength;
    float surfaceEnabled;
} ubuf;

layout(binding = 1) uniform sampler2D sceneSource;
layout(binding = 2) uniform sampler2D waterRippleMask;
layout(binding = 3) uniform sampler2D waterRippleNormal;

void main()
{
    vec2 uv = qt_TexCoord0;

    // The reference scene enables PERSPECTIVE with identity quad points, so
    // the inverse square-to-quad transform resolves exactly to the source UV.
    vec2 coordinates = uv;
    vec2 secondaryCoordinates = coordinates * 1.333;
    float speed = ubuf.waterRippleSpeed;
    float animationPhase = ubuf.sceneTime * speed * speed;

    vec4 rippleCoordinates;
    rippleCoordinates.xy = coordinates + vec2(animationPhase);
    rippleCoordinates.zw = secondaryCoordinates - vec2(animationPhase);
    float sourceAspect = ubuf.viewportSize.x / max(ubuf.viewportSize.y, 1.0);
    rippleCoordinates.xz *= sourceAspect;

    // WPE's normal sampler repeats. Qt Quick textures are not guaranteed to
    // expose that sampler state, so wrap explicitly before both samples.
    vec3 n1 = texture(waterRippleNormal, fract(rippleCoordinates.xy)).xyz * 2.0 - 1.0;
    vec3 n2 = texture(waterRippleNormal, fract(rippleCoordinates.zw)).xyz * 2.0 - 1.0;
    vec3 normal = normalize(vec3(n1.xy + n2.xy, n1.z));

    float mask = texture(waterRippleMask, uv).r
               * clamp(ubuf.surfaceEnabled, 0.0, 1.0);
    float strength = ubuf.waterRippleStrength;
    vec2 warpedUv = clamp(
        uv + normal.xy * strength * strength * mask,
        vec2(0.0),
        vec2(1.0)
    );

    // This is a replacement pass, not a translucent effect overlay. Pixels
    // outside the scalar mask sample the original source at the original UV.
    fragColor = texture(sceneSource, warpedUv) * ubuf.qt_Opacity;
}
