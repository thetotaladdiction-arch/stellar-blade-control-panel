#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 rigSize;
    vec2 wristOffset;
    vec2 clothOffset;
    float shoulderBend;
    float elbowBend;
} ubuf;

layout(binding = 2) uniform sampler2D weights;
layout(binding = 3) uniform sampler2D clothTipWeight;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;

    // RGB is a normalized shoulder/elbow/wrist skinning triplet frozen from
    // the approved connected assembly. The three channels sum to one across
    // every occupied pixel, so the sleeve, cuff, glove and cloth stay joined.
    vec3 boneWeight = texture(weights, qt_MultiTexCoord0).rgb;
    float clothTipInfluence = texture(clothTipWeight, qt_MultiTexCoord0).r;
    float occupied = min(1.0, boneWeight.r + boneWeight.g + boneWeight.b);
    vec2 perpendicular = vec2(-ubuf.wristOffset.y, ubuf.wristOffset.x);

    vec2 shoulderDelta = ubuf.wristOffset * 0.08
                       + perpendicular * ubuf.shoulderBend;
    vec2 elbowDelta = ubuf.wristOffset * 0.47
                    + perpendicular * ubuf.elbowBend;
    vec2 wristDelta = ubuf.wristOffset;
    vec2 normalizedDelta = boneWeight.r * shoulderDelta
                         + boneWeight.g * elbowDelta
                         + boneWeight.b * wristDelta;
    // The cloth base follows the glove through the wrist weight. Only the
    // authored tip map receives the delayed follower offset, eliminating the
    // rigid-card motion and keeping the contact edge joined to the glove.
    normalizedDelta += ubuf.clothOffset * clothTipInfluence;

    vec4 displaced = qt_Vertex;
    displaced.xy += normalizedDelta * ubuf.rigSize * occupied;
    gl_Position = ubuf.qt_Matrix * displaced;
}
