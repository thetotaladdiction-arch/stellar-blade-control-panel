#version 440

layout(location = 0) in vec2 qt_TexCoord0;
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

void main()
{
    float coverage = texture(source, qt_TexCoord0).a;
    fragColor = vec4(vec3(coverage), coverage) * ubuf.qt_Opacity;
}
