#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 shaftOrigin;
    vec2 shaftDirection;
    float shaftOpacity;
    float sceneTime;
    float shaftIndex;
} ubuf;

layout(binding = 1) uniform sampler2D depthMask;
layout(binding = 2) uniform sampler2D keepoutMask;

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 direction = normalize(ubuf.shaftDirection);
    vec2 perpendicular = vec2(-direction.y, direction.x);
    vec2 delta = uv - ubuf.shaftOrigin;
    float along = dot(delta, direction);
    float across = abs(dot(delta, perpendicular));
    float width = 0.055 + ubuf.shaftIndex * 0.018 + max(along, 0.0) * 0.16;
    float beam = smoothstep(width, 0.0, across) * smoothstep(-0.04, 0.10, along);
    beam *= exp(-max(along, 0.0) * 0.74);
    beam *= 0.92 + 0.08 * sin(uv.y * 36.0 + ubuf.sceneTime * 0.23 + ubuf.shaftIndex);
    float depthGate = smoothstep(0.02, 0.18, texture(depthMask, uv).r);
    float keepout = texture(keepoutMask, uv).r;
    float alpha = beam * depthGate * (1.0 - keepout)
                  * max(ubuf.shaftOpacity, 0.0);
    vec3 color = mix(vec3(0.28, 0.43, 0.54), vec3(0.55, 0.68, 0.75), uv.y);
    fragColor = vec4(color * alpha, alpha) * ubuf.qt_Opacity;
}
